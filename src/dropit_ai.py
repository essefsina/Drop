"""DropIt AI file search — semantic retrieval over the shared folder.

No generative AI, no chat, no cloud, no accounts. Three small local models:
  - MiniLM (text): matches prompts against file names + document contents.
  - CLIP (vision): matches prompts against what is *in* pictures.
  - RapidOCR: reads text inside images (indexed for search, shown in chat).
All models ship inside DropIt's own folder (ai_model/) — nothing to download.

Public API used by dropit.py:
    search_files(directory, data_dir, query, top_k=8) -> dict
    index_status(directory, data_dir) -> dict
    ocr_image(directory, name) -> dict   (transcribe one image for the chat)

Heavy deps (onnxruntime/tokenizers/numpy/Pillow/rapidocr) are imported
lazily so dropit.py stays light until the first AI search.
"""

import os
import pickle
import re
import sys
import threading
import time

INDEX_VERSION = 5  # v2.7.83: OCR confidence filter (0.70) changes
# indexed stems, and search gains an exact-keyword floor; bump so old
# indexes (with junk OCR tokens and no exact floor) are rebuilt once.


def _index_version():
    """Index version includes available components: installing a new
    capability (OCR/vision) invalidates the old index so files get
    re-embedded with it. Never silently serves a stale index."""
    v = INDEX_VERSION
    try:
        import rapidocr_onnxruntime  # noqa: F401
        v += 10
    except ImportError:
        pass
    try:
        import PIL.Image  # noqa: F401
        v += 20
    except ImportError:
        pass
    return v


def component_status():
    """Which AI components are actually ready on this machine."""
    st = {"search": model_ready(), "vision": False, "ocr": False,
          "translate": False, "missing": []}
    try:
        import PIL.Image  # noqa: F401
        st["vision"] = clip_ready()
        if not clip_ready():
            st["missing"].append("ai_model/clip files")
    except ImportError:
        st["missing"].append("Pillow")
    try:
        import rapidocr_onnxruntime  # noqa: F401
        st["ocr"] = True
    except ImportError:
        st["missing"].append("rapidocr-onnxruntime")
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        st["translate"] = True
    except ImportError:
        st["missing"].append("onnxruntime/tokenizers")
    if not model_ready():
        st["missing"].append("ai_model/minilm files")
    return st
MAX_TEXT_CHARS = 2000       # per-file text fed to the embedder
MAX_TOKENS = 256            # MiniLM input length
CLIP_TOKENS = 77            # CLIP text input length
MIN_SCORE = 0.30            # MiniLM text threshold
CLIP_MIN_SCORE = 0.25       # CLIP vision floor (adaptive cutoff above)
FILENAME_BOOST = 0.15       # exact filename substring match bonus

_sess = None
_tok = None
_clip_v = None
_clip_t = None
_clip_tok = None
_ocr = None
_model_lock = threading.Lock()
# v2.8.40: RLock, not Lock -- search_files takes this lock
# non-blocking and then calls build_index, which takes it again
# in the same thread (a plain Lock would deadlock there).
_index_lock = threading.RLock()
_ocr_lock = threading.Lock()
_transcribe_lock = threading.Lock()


def _transcribe_cache_path(data_dir):
    return os.path.join(data_dir, "transcribe_cache.json")


def _transcribe_cache_get(data_dir, fpath):
    """Cached transcription for one file, or None on a miss.

    Keyed by path + mtime + size, so an edited file re-transcribes.
    Only used when the server passes its data dir (transcribe paths);
    the index path does not use it (it already skips unchanged files).
    """
    if not data_dir:
        return None
    try:
        mtime = os.path.getmtime(fpath)
        size = os.path.getsize(fpath)
    except OSError:
        return None
    try:
        import json as _json
        with open(_transcribe_cache_path(data_dir),
                  encoding="utf-8") as f:
            cache = _json.load(f)
    except Exception:
        return None
    if not isinstance(cache, dict):
        return None
    ent = cache.get("%s|%s|%s" % (os.path.abspath(fpath), mtime, size))
    if isinstance(ent, dict) and isinstance(ent.get("text"), str):
        return ent["text"]
    return None


def _transcribe_cache_put(data_dir, fpath, text):
    if not data_dir or not isinstance(text, str):
        return
    try:
        mtime = os.path.getmtime(fpath)
        size = os.path.getsize(fpath)
    except OSError:
        return
    import json as _json
    path = _transcribe_cache_path(data_dir)
    with _transcribe_lock:
        try:
            with open(path, encoding="utf-8") as f:
                cache = _json.load(f)
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}
        cache["%s|%s|%s" % (os.path.abspath(fpath), mtime, size)] = {
            "text": text}
        # cap: drop oldest entries past 500 files
        while len(cache) > 500:
            cache.pop(next(iter(cache)))
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(cache, f)
        except OSError:
            pass


def _model_roots():
    """Candidate ai_model locations (source / exe / PyInstaller bundle)."""
    roots = [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ai_model")]
    exe = sys.executable
    if exe:
        roots.append(os.path.join(os.path.dirname(os.path.abspath(exe)),
                                  "ai_model"))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(os.path.join(meipass, "ai_model"))
    return roots


def _find(sub, *files):
    for r in _model_roots():
        d = os.path.join(r, sub)
        if all(os.path.isfile(os.path.join(d, f)) for f in files):
            return d
    return None


def _minilm_dir():
    return _find("minilm", "model.onnx", "tokenizer.json")


def _clip_dir():
    return _find("clip", "vision_model_quantized.onnx",
                 "text_model_quantized.onnx", "tokenizer.json")


def model_ready():
    return _minilm_dir() is not None


def _get_model():
    global _sess, _tok
    if _sess is None:
        with _model_lock:
            if _sess is None:
                import onnxruntime as ort
                from tokenizers import Tokenizer
                md = _minilm_dir()
                _sess = ort.InferenceSession(
                    os.path.join(md, "model.onnx"),
                    providers=["CPUExecutionProvider"])
                _tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
                _tok.enable_truncation(max_length=MAX_TOKENS)
                _tok.enable_padding(length=MAX_TOKENS)
    return _sess, _tok


def _encode(texts):
    """MiniLM: texts -> L2-normalized float32 vectors."""
    import numpy as np
    sess, tok = _get_model()
    batch = tok.encode_batch(texts)
    ids = np.array([e.ids for e in batch], dtype=np.int64)
    mask = np.array([e.attention_mask for e in batch], dtype=np.int64)
    feeds = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in [i.name for i in sess.get_inputs()]:
        feeds["token_type_ids"] = np.array(
            [e.type_ids for e in batch], dtype=np.int64)
    last = sess.run(None, feeds)[0]
    m = mask[..., None].astype(np.float32)
    summed = (last * m).sum(axis=1)
    counts = np.maximum(m.sum(axis=1), 1e-9)
    v = summed / counts
    norms = np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    return (v / norms).astype(np.float32)


# ---------------------------------------------------------- CLIP (vision)
CLIP_MEAN = None  # filled lazily to keep numpy import lazy
CLIP_STD = None


def _clip_models():
    global _clip_v, _clip_t, _clip_tok
    if _clip_v is None:
        with _model_lock:
            if _clip_v is None:
                import onnxruntime as ort
                from tokenizers import Tokenizer
                md = _clip_dir()
                if md is None:
                    raise RuntimeError("clip model missing")
                _clip_v = ort.InferenceSession(
                    os.path.join(md, "vision_model_quantized.onnx"),
                    providers=["CPUExecutionProvider"])
                _clip_t = ort.InferenceSession(
                    os.path.join(md, "text_model_quantized.onnx"),
                    providers=["CPUExecutionProvider"])
                _clip_tok = Tokenizer.from_file(
                    os.path.join(md, "tokenizer.json"))
                _clip_tok.enable_truncation(max_length=CLIP_TOKENS)
                _clip_tok.enable_padding(length=CLIP_TOKENS)
    return _clip_v, _clip_t, _clip_tok


def _clip_prep(path):
    """Image file -> CLIP pixel_values (1,3,224,224) float32."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((224, 224))
    a = np.asarray(im, dtype=np.float32) / 255.0
    mean = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
    std = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
    a = (a - mean) / std
    return a.transpose(2, 0, 1)[None].astype(np.float32)


def _clip_encode_images(paths):
    import numpy as np
    vsess, _, _ = _clip_models()
    batch = np.concatenate([_clip_prep(p) for p in paths], axis=0)
    v = vsess.run(None, {"pixel_values": batch})[0]
    norms = np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    return (v / norms).astype(np.float32)


def _clip_encode_text(texts):
    import numpy as np
    _, tsess, tok = _clip_models()
    batch = tok.encode_batch(texts)
    ids = np.array([e.ids for e in batch], dtype=np.int64)
    v = tsess.run(None, {"input_ids": ids})[0]
    norms = np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    return (v / norms).astype(np.float32)


def clip_ready():
    return _clip_dir() is not None


# ------------------------------------------------------------------- OCR
def _get_ocr():
    global _ocr
    if _ocr is None:
        with _model_lock:
            if _ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                _ocr = RapidOCR()
    return _ocr


def _ocr_image_array(fpath):
    """Load an image for OCR as a BGR numpy array via PIL, or None.

    PIL fixes three silent failure classes of the old path-based cv2 read:
    EXIF orientation (phone photos stored sideways), non-ASCII file paths
    (cv2.imread returns None for them on Windows), and formats/modes cv2
    chokes on (palette/RGBA PNGs, TIFF, JFIF). Long side capped at 3200px
    — the detector downscales internally anyway; this just bounds cost.
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps
        with Image.open(fpath) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            if max(w, h) > 3200:
                s = 3200 / max(w, h)
                im = im.resize((max(1, int(w * s)), max(1, int(h * s))),
                               Image.LANCZOS)
            elif max(w, h) < 600:
                # Small screenshots/photos: 2x upscale gives the detector
                # more pixels for tiny text (safety net; measured clean
                # text already reads at 1x, this only helps small text).
                im = im.resize((w * 2, h * 2), Image.LANCZOS)
            return np.asarray(im)[:, :, ::-1].copy()
    except Exception:
        return None


def _run_ocr(fpath):
    """One OCR pass. Serialized: the shared engine does not tolerate
    concurrent calls from the server's request threads, and the failures
    were silent — an empty result that then got cached as 'no text'."""
    ocr = _get_ocr()
    arr = _ocr_image_array(fpath)
    with _ocr_lock:
        res, _ = ocr(arr if arr is not None else fpath)
    if not res:
        return ""
    # v2.7.83: drop low-confidence fragments. RapidOCR scores real words
    # ~0.96-1.0 on the test corpus; junk fragments (partial plates,
    # stray marks) scored 0.62-0.68. A 0.70 floor drops the junk while
    # keeping every real word observed. Entries without a score are kept.
    kept = []
    for t in res:
        if len(t) > 1 and t[1]:
            score = t[2] if len(t) > 2 and isinstance(t[2], (int, float)) else 1.0
            if score >= 0.70:
                kept.append(t[1])
    return "\n".join(kept).strip()


def _ocr_text(fpath):
    """Transcribed text in an image. Empty string on failure/blank."""
    try:
        return _run_ocr(fpath)
    except Exception:
        return ""


def _ocr_text_strict(fpath):
    """Like _ocr_text but raises with the real error (for diagnostics)."""
    return _run_ocr(fpath)


TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json",
    ".py", ".js", ".ts", ".html", ".htm", ".css", ".xml", ".yaml",
    ".yml", ".ini", ".cfg", ".toml", ".sh", ".bat", ".ps1", ".java",
    ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sql", ".rst",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
              ".jfif", ".tif", ".tiff"}


def _index_path(data_dir):
    return os.path.join(data_dir, "ai_index.pkl")


def full_text(fpath, data_dir=None):
    """Complete readable text for one file (transcribe path). No 2000-char
    cap, paragraph breaks preserved. Never raises. Images served from
    the transcribe cache on repeat calls (see ocr_image)."""
    try:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in IMAGE_EXTS:
            cached = _transcribe_cache_get(data_dir, fpath)
            if cached is not None:
                return cached
            text = _ocr_text(fpath)
            _transcribe_cache_put(data_dir, fpath, text)
            return text
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(fpath)
                parts = []
                for page in reader.pages[:100]:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t.strip())
                return "\n\n".join(parts)
            except Exception:
                return ""
        if ext == ".docx":
            try:
                import docx
                doc = docx.Document(fpath)
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception:
                return ""
        if ext in TEXT_EXTS:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                return f.read(500_000)
        # fallback: route through the standard extractor
        return extract_text(fpath)
    except Exception:
        return ""


def extract_text(fpath):
    """Best-effort searchable text for one file. Never raises.
    Images contribute their OCR transcription."""
    try:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in IMAGE_EXTS:
            return _ocr_text(fpath)
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(fpath)
                parts = []
                for page in reader.pages[:20]:
                    parts.append(page.extract_text() or "")
                    if sum(len(p) for p in parts) > MAX_TEXT_CHARS:
                        break
                return " ".join(parts)[:MAX_TEXT_CHARS]
            except Exception:
                return ""
        if ext == ".docx":
            try:
                import docx
                doc = docx.Document(fpath)
                text = "\n".join(p.text for p in doc.paragraphs)
                return text[:MAX_TEXT_CHARS]
            except Exception:
                return ""
        if ext in TEXT_EXTS:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                return f.read(MAX_TEXT_CHARS)
        return ""
    except Exception:
        return ""


def _describe(name, text):
    """Single string the text embedder sees for a file."""
    base = os.path.splitext(name)[0].replace("_", " ").replace("-", " ")
    if text and text.strip():
        return "%s. %s" % (base, text.strip()[:MAX_TEXT_CHARS])
    return base


def _load_index(data_dir):
    p = _index_path(data_dir)
    if not os.path.isfile(p):
        return {"v": _index_version(), "files": {}, "order": []}
    try:
        with open(p, "rb") as f:
            idx = pickle.load(f)
        if idx.get("v") != _index_version():
            return {"v": _index_version(), "files": {}, "order": []}
        return idx
    except Exception:
        return {"v": _index_version(), "files": {}, "order": []}


def _save_index(data_dir, index):
    # v2.8.40: atomic write -- a concurrent _load_index must never
    # read a half-written pickle (search now reads the index while
    # a background build is saving it, so torn reads became likely).
    try:
        os.makedirs(data_dir, exist_ok=True)
        tmp = os.path.join(data_dir, "ai_index.pkl.tmp.%d.%d" % (
            os.getpid(), threading.get_ident()))
        with open(tmp, "wb") as f:
            pickle.dump(index, f)
        os.replace(tmp, _index_path(data_dir))
    except Exception:
        pass


def build_index(directory, data_dir, progress_cb=None):
    """(Re)build the embedding index. Only new/changed files are embedded."""
    with _index_lock:
        index = _load_index(data_dir)
        files = index.get("files", {})

        try:
            names = [n for n in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, n))]
        except OSError:
            names = []

        _before = len(files)
        for n in list(files):
            if n not in names:
                del files[n]
        _removed = _before - len(files)

        todo = []
        for n in names:
            fp = os.path.join(directory, n)
            try:
                mtime = os.path.getmtime(fp)
                size = os.path.getsize(fp)
            except OSError:
                continue
            rec = files.get(n)
            if rec and rec.get("mtime") == mtime and rec.get("size") == size \
                    and "vec" in rec and rec.get("stems_v") == 2:
                # v2.8.40: an image rec with no OCR verdict (indexed
                # while the engine was missing) is re-run once, so
                # it gets a verdict recorded -- otherwise it would
                # re-OCR on every page load forever, with no verdict
                # ever landing in the index.
                if is_image(n) and "has_ocr" not in rec \
                        and _ocr_available():
                    pass
                else:
                    continue
            todo.append(n)

        total = len(todo)
        # text embeddings (all files; images contribute OCR transcription)
        texts = [extract_text(os.path.join(directory, n)) for n in todo]
        descs = [_describe(n, t) for n, t in zip(todo, texts)]
        vecs = _encode(descs) if descs else []
        # vision embeddings (images only)
        img_idx = [i for i, n in enumerate(todo)
                   if is_image(n) and clip_ready()]
        cvecs = {}
        if img_idx:
            try:
                embs = _clip_encode_images(
                    [os.path.join(directory, todo[i]) for i in img_idx])
                for k, i in enumerate(img_idx):
                    cvecs[i] = embs[k]
            except Exception:
                pass

        for i, n in enumerate(todo):
            fp = os.path.join(directory, n)
            try:
                mtime = os.path.getmtime(fp)
                size = os.path.getsize(fp)
            except OSError:
                continue
            rec = {"vec": vecs[i], "mtime": mtime, "size": size,
                   "stems": sorted(_tokens(n + " " + texts[i])),
                   "stems_v": 2}
            if i in cvecs:
                rec["vec_clip"] = cvecs[i]
            if is_image(n):
                # Only record a verdict when the OCR engine actually ran;
                # a missing engine must not poison the file as "no text".
                if _ocr_available():
                    rec["has_ocr"] = bool(texts[i].strip())
                    rec["ocr_tries"] = 0
            else:
                rec["has_text"] = bool(texts[i].strip())
            files[n] = rec
            if progress_cb:
                progress_cb(i + 1, total)

        index["v"] = _index_version()
        index["files"] = files
        index["order"] = sorted(files)
        # v2.8.41: a no-op build (nothing embedded, nothing
        # removed) must NOT rewrite ai_index.pkl. The old code
        # saved unconditionally, so every startup / search-time
        # build re-wrote the file with the snapshot it loaded
        # at the start -- wiping any verdict another thread
        # (e.g. /api/aicheck healing rechecks) had recorded
        # meanwhile. No changes, no write.
        if total or _removed:
            _save_index(data_dir, index)
        return {"indexed": len(files), "embedded_now": total}


_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"


def _tokens(text):
    """Search tokens for a string: stemmed latin words plus CJK runs
    and their bigrams (CJK has no word spaces; bigrams are the closest
    thing to keywords)."""
    out = {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())}
    for run in re.findall("[" + _CJK + "]+", text or ""):
        out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


_word_vocab = None


def _real_words():
    """Whole words in the bundled MiniLM tokenizer's vocabulary. Real
    English words ('beach', 'charger') are in it; keyboard mash
    ('shdbdue7') is not — a grounding oracle for the gibberish guard."""
    global _word_vocab
    if _word_vocab is None:
        _word_vocab = set()
        try:
            import json as _json
            d = _minilm_dir()
            if d:
                with open(os.path.join(d, "tokenizer.json"),
                          encoding="utf-8") as f:
                    vocab = _json.load(f)["model"]["vocab"]
                _word_vocab = {t for t in vocab if len(t) >= 3
                               and t.isalpha() and not t.startswith("##")}
        except Exception:  # noqa: BLE001
            pass
    return _word_vocab


def _stem(w):
    """Crude English stemming so 'screenshots' matches 'screenshot'."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


def _parse_date_filter(query):
    """Return (cleaned_query, since_ts|None, until_ts|None).

    Handles relative ("last week", "yesterday") and absolute
    ("oct 2", "october 5", "10/2") dates. Absolute dates become a
    single-day range; relative dates run until now.
    """
    import calendar
    now = time.time()
    day = 86400
    q = query.lower()
    since = until = None
    patterns = [
        (r"\bfrom yesterday\b|\byesterday\b", now - day, now),
        (r"\bfrom today\b|\btoday\b", now - day, now),
        (r"\bfrom last week\b|\blast week\b|\bpast week\b",
         now - 7 * day, now),
        (r"\bfrom last month\b|\blast month\b|\bpast month\b",
         now - 30 * day, now),
        (r"\bfrom last year\b|\blast year\b|\bpast year\b",
         now - 365 * day, now),
    ]
    for pat, s, u in patterns:
        if re.search(pat, q):
            since, until = s, u
            q = re.sub(pat, " ", q)
            break
    # absolute: "oct 2", "october 5", "oct. 2"
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    if since is None:
        m = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})\b", q)
        if m:
            mon = months[m.group(1)[:3]]
            daynum = int(m.group(2))
            yr = time.localtime(now).tm_year
            ts = None
            try:
                ts = time.mktime((yr, mon, daynum, 0, 0, 0, 0, 0, -1))
            except (OverflowError, ValueError):
                pass
            if ts and ts > now:  # hasn't happened yet → last year
                try:
                    ts = time.mktime((yr - 1, mon, daynum, 0, 0, 0, 0, 0, -1))
                except (OverflowError, ValueError):
                    ts = None
            if ts:
                since, until = ts, ts + day
                q = q.replace(m.group(0), " ")
    # absolute numeric: "10/2", "10-2" (month/day)
    if since is None:
        m = re.search(r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])\b", q)
        if m:
            mon, daynum = int(m.group(1)), int(m.group(2))
            yr = time.localtime(now).tm_year
            ts = None
            try:
                ts = time.mktime((yr, mon, daynum, 0, 0, 0, 0, 0, -1))
            except (OverflowError, ValueError):
                pass
            if ts and ts > now:
                try:
                    ts = time.mktime((yr - 1, mon, daynum, 0, 0, 0, 0, 0, -1))
                except (OverflowError, ValueError):
                    ts = None
            if ts:
                since, until = ts, ts + day
                q = q.replace(m.group(0), " ")
    m = re.search(r"\b(19|20)\d{2}\b", q)
    if m and since is None:
        year = int(m.group(0))
        since = calendar.timegm((year, 1, 1, 0, 0, 0))
        until = calendar.timegm((year + 1, 1, 1, 0, 0, 0))
        q = q.replace(m.group(0), " ")
    q = re.sub(r"\s+", " ", q).strip(" ,.")
    return q, since, until


def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def _build_running():
    """True while any thread holds the index build lock (startup
    preload, upload build, or a background build below). Probed
    non-blocking; never waits."""
    if _index_lock.acquire(blocking=False):
        _index_lock.release()
        return False
    return True


def _bg_build_safe(directory, data_dir):
    try:
        build_index(directory, data_dir)
    except Exception:  # noqa: BLE001 - background warm-up never breaks a request
        pass


def _ensure_background_build(directory, data_dir):
    """v2.8.41: make sure the index is being built in the
    BACKGROUND, never on a request thread. Called from search
    and from /api/files, so the index warms up as soon as the
    page loads. Single-flight: if a build (preload, upload, or
    an earlier background one) is already running, this is a
    no-op; if every on-disk file is already indexed, it is a
    no-op too. Returns at once in all cases."""
    try:
        index = _load_index(data_dir)
        have = set(index.get("files", {}))
        try:
            names = [n for n in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, n))]
        except OSError:
            return
        if all(n in have for n in names):
            return
    except Exception:  # noqa: BLE001 - never break the caller
        return
    if _build_running():
        return
    threading.Thread(target=_bg_build_safe, args=(directory, data_dir),
                     daemon=True).start()


def _live_keyword_hits(directory, names, exact_tokens, since, until):
    """v2.8.41: exact-keyword hits for files NOT yet in the
    embedding index, computed live with no models and no OCR:
    filename stems plus readable text for text-ish files
    (plain text, PDF, Word -- the fast extractors only).
    Images contribute their filename only; OCR text for them
    arrives with the background build. A file whose stems
    contain EVERY query token is an exact hit (score 0.90,
    the same floor the indexed path uses), so a cold-start
    search still answers filename / document-word queries
    instantly instead of timing out on a full index build.
    Returns [(score, name, rec, kind, exact_hit)] in the
    scored-list shape. Never raises; per-file failures skip
    that file."""
    out = []
    if not exact_tokens:
        return out
    for n in names:
        try:
            fp = os.path.join(directory, n)
            if not os.path.isfile(fp):
                continue
            mtime = os.path.getmtime(fp)
            if since and mtime < since:
                continue
            if until and mtime >= until:
                continue
            name_stems = set(_tokens(n))
            text_stems = set()
            has_text = False
            if not is_image(n):
                try:
                    _t = extract_text(fp)
                    has_text = bool(_t.strip())
                    text_stems = _tokens(_t)
                except Exception:  # noqa: BLE001 - one bad file skips
                    pass
            if not exact_tokens <= (name_stems | text_stems):
                continue
            out.append((0.90, n,
                        {"size": os.path.getsize(fp),
                         "mtime": int(mtime),
                         "has_text": has_text},
                        "text", True))
        except OSError:
            continue
    return out


def search_files_timed(directory, data_dir, query, top_k=50,
                       timeout=None):
    """Bounded search_files (v2.8.1): a search must ALWAYS terminate.
    The unbounded version can block indefinitely -- build_index takes
    _index_lock (held by an upload-triggered background build), the
    first model load is slow, and OCR/CLIP over a big folder takes
    minutes -- and the web Find had no timeout at all, so the typing
    indicator spun forever. Here the real search runs on a daemon
    thread; if it has not answered within `timeout` seconds the
    caller gets a timeout answer at once (the thread keeps running
    in the background and may still finish indexing; it never
    blocks a later search's answer). Default 75s; the
    DROPIT_SEARCH_TIMEOUT env var overrides it (tests use a small
    value to prove the mechanism without waiting 75s)."""
    if timeout is None:
        try:
            timeout = float(os.environ.get("DROPIT_SEARCH_TIMEOUT", "75"))
        except ValueError:
            timeout = 75.0
    box = {}

    def _run():
        try:
            box["r"] = search_files(directory, data_dir, query, top_k)
        except Exception:  # noqa: BLE001 - search_files never raises
            box["r"] = {"ok": False, "results": [], "message": "error"}

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if "r" in box:
        return box["r"]
    return {"ok": False, "results": [], "message": "timeout"}


def search_files(directory, data_dir, query, top_k=50):
    """Prompt in -> ranked file list out. Never raises."""
    import numpy as np

    try:
        if not model_ready():
            return {"ok": False, "results": [], "message": "no_model"}
        # v2.8.41: a search NEVER builds the index. The 2.8.40
        # code took the lock when free and ran the whole build
        # inline -- on the desktop app (which never ran the
        # startup preload) the first search after a restart WAS
        # the full OCR + CLIP + embedding pass over every
        # unindexed file: 40s on small images, past the 75s
        # timeout on phone-resolution photos, so every first
        # search answered "took too long". Instead: kick off a
        # single-flight BACKGROUND build and search the index
        # as it stands right now, plus a live keyword fallback
        # (below) for files the index has not reached yet.
        # A search now answers in seconds from a cold start.
        _ensure_background_build(directory, data_dir)
        index = _load_index(data_dir)
        files = index.get("files", {})
        try:
            _disk = [n for n in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, n))]
        except OSError:
            _disk = []
        _missing = [n for n in _disk if n not in files]
        _indexing = bool(_missing) or _build_running()
        if not files and not _disk:
            return {"ok": True, "results": [], "message": "empty",
                    "indexing": False, "indexed": 0, "pending": 0}

        q, since, until = _parse_date_filter(query or "")
        if not q:
            # pure date query ("oct 2") → list everything on that date
            if since:
                out = [
                    {"name": n, "size": files[n].get("size", 0),
                     "mtime": int(files[n].get("mtime", 0))}
                    for n in index.get("order", [])
                    if n in files and since <= files[n].get("mtime", 0)
                    and (until is None or files[n].get("mtime", 0) < until)
                ]
                # v2.8.41: unindexed files still have a date --
                # stat them live so a cold-start date query
                # lists them too instead of answering empty.
                for n in _missing:
                    try:
                        _mt = os.path.getmtime(os.path.join(directory, n))
                    except OSError:
                        continue
                    if since <= _mt and (until is None or _mt < until):
                        out.append({"name": n,
                                    "size": os.path.getsize(
                                        os.path.join(directory, n)),
                                    "mtime": int(_mt)})
                out.sort(key=lambda r: r["mtime"], reverse=True)
                return {"ok": True, "results": out[:top_k],
                        "message": f"{len(out)} files",
                        "indexing": _indexing,
                        "indexed": len(files), "pending": len(_missing)}
            return {"ok": True, "results": [], "message": "empty_query",
                    "indexing": _indexing,
                    "indexed": len(files), "pending": len(_missing)}

        qlow = q.lower()
        # v2.7.81: scoring restored to the v2.7.71 behavior Essef called
        # perfect (the version on git main) — one fixed bar per signal for
        # every query. v2.7.83 keeps those bars (text 0.30, vision 0.25)
        # and adds three precision rules on top, without loosening them:
        #  (1) exact keyword floor: a query whose tokens ALL appear in a
        #      file's indexed stems (filename + OCR/document text) is a
        #      direct match — it must surface even when the keyword is
        #      buried in a long text and the embedding dilutes below 0.30.
        #  (2) gibberish guard: a query of only non-vocabulary tokens with
        #      no exact/filename hit anywhere returns zero results.
        #  (3) when an exact match exists, non-exact results below 0.50
        #      are dropped (weak vision guesses and embedding noise
        #      alike); and for OCR-bearing images without an exact hit,
        #      the text signal only counts at >= 0.45 — below that only
        #      vision can win the file, which is what saves real photos
        #      while killing text-image text noise like "beach" ->
        #      a GARDEN text image at 0.353.
        _qtoks = _tokens(q)
        _cjk_query = any(ord(c) > 127 and c.isalpha() for c in q)
        _text_bar = MIN_SCORE
        _clip_bar = CLIP_MIN_SCORE
        _stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on",
                 "for", "with", "is", "at", "by"}
        _exact_tokens = _qtoks - _stop
        _has_exact = False
        if _exact_tokens:
            for _n in index.get("order", []):
                _r = files.get(_n)
                if _r and _exact_tokens <= set(_r.get("stems") or []):
                    _has_exact = True
                    break
        if not _has_exact and not _cjk_query:
            _qw = set(re.findall(r"[a-z0-9]+", qlow))
            _vocab = _real_words()
            _name_hit = False
            for _n in index.get("order", []):
                _nw = set(_stem(w) for w in
                          re.findall(r"[a-z0-9]+", _n.lower()))
                if _qw and set(_stem(w) for w in _qw) & _nw:
                    _name_hit = True
                    break
            # Grounded = in the MiniLM whole-word vocab, or tokenized
            # into at most 4 real subword pieces without [UNK].
            # "motorbike" -> motor+bi+ke (3, grounded, real word);
            # "safkjaeoifjeoije" -> 8 fragments (gibberish).
            def _grounded(_w):
                if _w in _vocab:
                    return True
                try:
                    _sess, _tok = _get_model()
                    _pieces = [t for t in _tok.encode(_w).tokens
                               if t not in ("[CLS]", "[SEP]", "[PAD]")]
                    return bool(_pieces) and len(_pieces) <= 4 \
                        and "[UNK]" not in _pieces
                except Exception:
                    return False
            if _qw and not _name_hit and not any(_grounded(w) for w in _qw):
                return {"ok": True, "results": [], "message": "none",
                        "indexing": _indexing,
                        "indexed": len(files), "pending": len(_missing)}

        qvec = _encode([q])[0]
        qclip = _clip_encode_text([q])[0] if clip_ready() else None

        def _score_all(text_bar, clip_bar):
            scored = []
            for name in index.get("order", []):
                rec = files.get(name)
                if not rec or "vec" not in rec:
                    continue
                if since and rec.get("mtime", 0) < since:
                    continue
                if until and rec.get("mtime", 0) >= until:
                    continue
                img = is_image(name)
                # word-level filename match (stemmed: "screenshots" hits
                # "screenshot"; not substring: "logo" != "catalogue")
                namewords = set(re.findall(r"[a-z0-9]+", name.lower()))
                qwords = set(re.findall(r"[a-z0-9]+", qlow))
                qstems = set(_stem(w) for w in qwords)
                nstems = set(_stem(w) for w in namewords)
                word_hit = bool(qstems & nstems)
                text_s = float(np.dot(qvec, rec["vec"]))
                if img and not rec.get("has_ocr") and not word_hit:
                    # filename-only image descriptions are noise: ignore unless
                    # the user literally typed (part of) the file's name
                    text_s = -1.0
                elif word_hit:
                    text_s += FILENAME_BOOST
                # CJK keyword hit: a Chinese/Japanese/Korean query whose
                # tokens (runs + bigrams) ALL appear in the file's indexed
                # text is an exact keyword match — floor it like a filename
                # hit.
                if _cjk_query and _qtoks:
                    _fstems = set(rec.get("stems") or [])
                    if _fstems and _qtoks <= _fstems:
                        text_s = max(text_s, 0.60)
                # v2.7.83 exact keyword floor (Latin too): every query
                # token in the file's stems = the word is literally in
                # the file (name, OCR text, or document text). Floor it
                # to 0.90 so a buried keyword is never diluted away by
                # the embedding, and so it outranks vision guesses.
                # Pure-stopword queries are exempt (they match everything).
                _exact_hit = bool(_exact_tokens) and _exact_tokens <= set(
                    rec.get("stems") or [])
                if _exact_hit:
                    text_s = max(text_s, 0.90)
                clip_s = -1.0
                if qclip is not None and "vec_clip" in rec:
                    clip_s = float(np.dot(qclip, rec["vec_clip"]))
                # separate signals: text needs 0.30, vision needs 0.25
                ok_text = text_s >= text_bar
                # v2.7.83: an OCR-bearing image whose text does not
                # literally contain the query is a weak text match below
                # 0.45 — short filename+OCR descriptions embed 0.30-0.37
                # against unrelated single words ("beach" vs a GARDEN
                # text image at 0.353). Below 0.45 the text signal is
                # ignored and only vision (CLIP) can win the file, which
                # is what saves real photos (a bike photo's CLIP score
                # still clears 0.25 even when its text score is dropped).
                if img and rec.get("has_ocr") and not _exact_hit \
                        and text_s < 0.45:
                    ok_text = False
                ok_clip = clip_s >= clip_bar
                if not (ok_text or ok_clip):
                    continue
                # best score + which signal won (for adaptive cutoff below)
                if ok_clip and (not ok_text or clip_s >= text_s):
                    scored.append((clip_s, name, rec, "clip", _exact_hit))
                else:
                    scored.append((text_s, name, rec, "text", _exact_hit))

            scored.sort(reverse=True, key=lambda t: t[0])
            return scored

        scored = _score_all(_text_bar, _clip_bar)
        # v2.8.41: files the index has not reached yet still
        # answer exact filename / document-word queries live
        # (no models, no OCR -- milliseconds). Without this a
        # cold-start search could only answer from an empty
        # index until the background build finished minutes
        # later. Fallback hits carry exact=True, so they
        # survive the exact filter below exactly like indexed
        # exact hits, and they never loosen the 0.30/0.25 bars.
        if _missing and _exact_tokens:
            scored.extend(_live_keyword_hits(
                directory, _missing, _exact_tokens, since, until))
            scored.sort(reverse=True, key=lambda t: t[0])
        # v2.7.83: when an exact keyword match exists, it outranks
        # everything else. Drop non-exact results below 0.50 — both
        # weak CLIP guesses and embedding noise (MiniLM gives unrelated
        # short descriptions 0.32-0.37, e.g. "rotated" vs a "rear side"
        # photo). Strong semantic matches (>= 0.50) still survive.
        if any(t[4] for t in scored):
            scored = [t for t in scored
                      if t[4] or t[0] >= 0.50]
        # Adaptive cutoff for vision: when a photo matches strongly, drop the
        # weak tail. (Fixed bars fail: "beach" scores 0.25 while random photos
        # score 0.23 — one bar either misses beach or lets in junk.)
        clip_scores = [s for s, _, _, k, _ in scored if k == "clip"]
        if clip_scores:
            clip_cutoff = max(_clip_bar, max(clip_scores) * 0.85)
            scored = [t for t in scored
                      if t[3] == "text" or t[0] >= clip_cutoff]
        results = []
        for score, name, rec, _, _ in scored[:top_k]:
            results.append({
                "name": name,
                "size": rec.get("size", 0),
                "mtime": int(rec.get("mtime", 0)),
                "score": round(score, 3),
                "image": is_image(name),
                # v2.7.83: search results gate the AI icon on this —
                # True only when the file actually has readable text.
                "has_text": bool(rec.get("has_ocr") if is_image(name)
                                 else rec.get("has_text")),
            })
        return {"ok": True, "results": results,
                "message": "none" if not results else "ok",
                "indexing": _indexing,
                "indexed": len(files), "pending": len(_missing)}
    except Exception as e:  # never break the server
        msg = str(e)
        if "onnxruntime" in msg or "tokenizers" in msg \
                or "No module named" in msg:
            return {"ok": False, "results": [], "message": "needs_setup"}
        return {"ok": False, "results": [], "message": "error",
                "error": msg[:200]}


def _ocr_available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def ocr_image(directory, name, data_dir=None):
    """Transcribe one image's text for the chat box. Never raises.

    Repeat transcriptions of an unchanged file are served from the
    transcribe cache (data_dir/transcribe_cache.json) instead of
    re-running OCR — the v2.7.83 fix for slow repeat taps.
    """
    try:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return {"ok": False, "text": "", "message": "needs_setup"}
        safe = re.sub(r"[^\w.\-() ]", "", name).strip()
        fp = os.path.join(directory, safe)
        if not os.path.isfile(fp) or not is_image(safe):
            return {"ok": False, "text": "", "message": "not_found"}
        cached = _transcribe_cache_get(data_dir, fp)
        if cached is not None:
            if not cached:
                return {"ok": True, "text": "",
                        "message": "blank",
                        "note": "No readable text found in this image.",
                        "cached": True}
            return {"ok": True, "text": cached, "message": "ok",
                    "cached": True}
        try:
            text = _ocr_text_strict(fp)
        except Exception as e:
            return {"ok": False, "text": "", "message": "error",
                    "note": str(e)[:200]}
        _transcribe_cache_put(data_dir, fp, text)
        if not text:
            return {"ok": True, "text": "",
                    "message": "blank",
                    "note": "No readable text found in this image."}
        return {"ok": True, "text": text, "message": "ok"}
    except Exception as e:
        msg = str(e)
        if "rapidocr" in msg or "No module named" in msg:
            return {"ok": False, "text": "", "message": "needs_setup"}
        return {"ok": False, "text": "", "message": "error"}


def index_status(directory, data_dir):
    """Light status for progress UI."""
    index = _load_index(data_dir)
    try:
        names = [n for n in os.listdir(directory)
                 if os.path.isfile(os.path.join(directory, n))]
    except OSError:
        names = []
    files = index.get("files", {})
    pending = sum(1 for n in names if n not in files)
    st = {"indexed": len(files), "files": len(names), "pending": pending,
          "model_ready": model_ready(), "clip_ready": clip_ready()}
    st.update(component_status())
    return st


def ai_eligible(directory, data_dir, name):
    """Fast check for the Shared Files AI button: True if the file has
    transcribable text. Uses the index only (no on-demand OCR); documents
    not yet indexed get a quick text peek."""
    try:
        index = _load_index(data_dir)
        rec = index.get("files", {}).get(name)
        if rec:
            return bool(rec.get("has_ocr") or rec.get("has_text"))
        if is_image(name):
            return False
        t = extract_text(os.path.join(directory, name))
        return bool(t.strip())
    except Exception:
        return False


def ai_state(directory, data_dir, name):
    """(has_text, known) for the Shared Files AI button.

    v2.8.41: a verdict recorded in the index IS durable --
    known=True the moment the index holds a has_ocr / has_text
    value for the file, whether it says "has text" or "no
    text". The 2.8.40 code kept text-less images "provisional"
    (unknown) until 3 OCR rechecks had accumulated, so every
    app restart re-ran a full OCR pass per text-less image
    through /api/aicheck -- the sparkle reloaded on every
    restart and took minutes, and a session that ended before
    all rechecks finished never accumulated them, so it never
    settled. The healing rechecks in file_has_text still exist
    for files the client explicitly checks (genuinely unknown
    files); they no longer gate known-ness. A file with no
    verdict recorded at all (indexed while the OCR engine was
    missing, or never indexed) still reports unknown, and the
    background build records its verdict once.
    The first value matches ai_eligible exactly.
    """
    try:
        index = _load_index(data_dir)
        rec = index.get("files", {}).get(name)
        if rec:
            if rec.get("has_ocr") or rec.get("has_text"):
                return True, True
            if "has_ocr" in rec or "has_text" in rec:
                return False, True  # verdict recorded: durable, no re-scan
            return False, False  # indexed, no verdict recorded
        if is_image(name):
            return False, False
        t = extract_text(os.path.join(directory, name))
        return bool(t.strip()), True
    except Exception:
        return False, False


def file_has_text(directory, data_dir, name):
    """True if the file has transcribable text (document text or image OCR).
    Used to decide whether the AI button shows for a file."""
    index = _load_index(data_dir)
    rec = index.get("files", {}).get(name)
    if rec:
        if rec.get("has_ocr") or rec.get("has_text"):
            return True
        # indexed but flagged empty → no button
        if "has_ocr" in rec or "has_text" in rec:
            # An indexing-time miss used to be trusted forever: one bad
            # moment (engine busy, models still loading) hid the AI button
            # for that photo permanently. Flagged-empty images get a few
            # live rechecks; a hit heals the record.
            if is_image(name) and rec.get("ocr_tries", 0) < 3:
                try:
                    t = extract_text(os.path.join(directory, name))
                except Exception:
                    t = ""
                with _index_lock:
                    idx = _load_index(data_dir)
                    r2 = idx.get("files", {}).get(name)
                    if r2 is not None:
                        r2["ocr_tries"] = r2.get("ocr_tries", 0) + 1
                        if t.strip():
                            r2["has_ocr"] = True
                        _save_index(data_dir, idx)
                return bool(t.strip())
            return False
    # not indexed yet: documents are eligible, images need an OCR check
    if not is_image(name):
        try:
            t = extract_text(os.path.join(directory, name))
            return bool(t.strip())
        except Exception:
            return False
    try:
        t = extract_text(os.path.join(directory, name))
        return bool(t.strip())
    except Exception:
        return False

