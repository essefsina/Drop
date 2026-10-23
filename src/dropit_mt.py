"""Local translation for DropIt - on-device, no accounts, no cloud.

Pipeline:
  1. Offline language detect (common-words + script ranges).
  2. English: return the text unchanged.
  3. Otherwise: load the cached Xenova opus-mt-{src}-en ONNX pair
     (downloaded once on first use, ~110 MB, kept under
     <data_dir>/mt_models/) and translate with onnxruntime.

Only needs onnxruntime + tokenizers + numpy (already bundled for AI search).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import urllib.request

_TIMEOUT = 30
_DL_TIMEOUT = 600
_CHUNK_TOKENS = 400

# --- local language detection ---------------------------------------------
# Common words per language (lowercase). Script ranges handled separately.
_COMMON = {
    "en": "the be to of and a in that have i it for not on with he as you do at is are was were this these those will would can could should has had been who what when where why how which their there then than they we our us your my me him her his she its an or but if so no yes all any some such only own same other into over after before between through during above below up down out off again further once here both each few more most nor too very just now don hello world thanks please good morning day man woman child house water bread",
    "es": "el la de que y a en un ser se no haber por con su para como estar tener los las del al lo le les me te nos os mi mis tu tus su sus este esta estos estas ese esa esos esas aquí hay más muy pero porque cuando donde cual cuales quien quienes cuyo cuya cuyos cuyas también tan tanto toda todo todos nada algo alguien siempre nunca jamás hoy ayer mañana ahora después antes durante entre hacia hasta desde sobre bajo tras durante mediante según sin sobre tras hola gracias favor buenos días mundo amigo casa agua está son",
    "fr": "le de un être et à il avoir ne je son que se qui ce dans en du elle au aux des les des du de la le les un une des du de la le la les un une et est sont était étaient être avoir avait avaient faire fait font allons allez ils elles nous vous ils elles on y en plus moins très bien mal oui non pas plus moins aussi ainsi donc car comme quand où comment pourquoi parce que lequel laquelle lesquels lesquelles dont duquel desquels bonjour tout tous toute toutes monde merci avec pour sur bon bonne jour nuit homme femme enfant maison eau pain fromage vin",
    "de": "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine einer eines einem einen als auch es an werden aus bei nach wird noch war waren haben hatte hatten sein sind war waren wurde wurden werden kann können muss müssen soll sollen will wollen darf dürfen mag mögen möchte möchten aber oder wenn dann denn doch nur schon noch sehr mehr weniger hier dort wo wohin woher warum wie was wer wen wem wessen welche welcher welches hallo danke bitte guten morgen welt mann frau kind haus wasser brot gut",
    "it": "il di che e la per un in è con non si una da come dei al del allo alla ai agli dal dallo dalla dai dagli nel nello nella nei negli sul sullo sulla sui sugli dal dello dalla dai dagli del dello della dei degli un uno una che chi cui dove quando perché come quanto quale quali quanto tutto tutti tutta tutte molto poco più meno bene male sì no forse sempre mai oggi ieri domani adesso dopo prima durante tra fra verso fino da a di in con su per tra fra ciao grazie prego buongiorno mondo uomo donna bambino casa acqua pane vino",
    "pt": "o de a e do da em um para com não uma os no se na por mais como mas foi ao ele dela dele isto isso aquilo aqui aí ali agora hoje ontem amanhã depois antes durante entre até desde sobre sob trás muito pouco mais menos bem mal sim não talvez sempre nunca hoje ontem amanhã olá obrigado obrigada favor bom dia mundo homem mulher criança casa água pão vinho são",
    "nl": "de het een van en in op dat is te voor met als zijn er aan door over tegen onder tussen naar uit om tot al niet geen wel zou zullen kunnen moeten mogen willen worden werd werden heeft hadden zijn was waren hallo dank bedankt goedemorgen wereld man vrouw kind huis water brood goed",
    "ru": "и в не на я быть он с а как по это она к у ты из мы вы они меня тебя себя нас вас их его её наш ваш их это то эти этот эта привет спасибо пожалуйста здравствуйте мир человек женщина ребёнок дом вода хлеб да нет хорошо",
    "hi": "और है के में से पर यह वह नहीं को ने का की तो भी अब जब तब क्या क्यों कैसे कहाँ कौन किस जिसे नमस्ते धन्यवाद कृपया दुनिया आदमी औरत बच्चा घर पानी रोटी अच्छा",
    "bn": "এবং হয় এর মধ্যে থেকে পর এই তা না কে কি কেন কিভাবে কোথায় নমস্কার ধন্যবাদ দয়া বিশ্ব মানুষ মহিলা শিশু বাড়ি পানি রুটি ভালো",
    "tr": "bir ve bu için de da ne ile çok olarak değil mi mu mü mı merhaba teşekkürler lütfen dünya adam kadın çocuk ev su ekmek iyi gün",
    "pl": "i w nie na z do się o jest jak że ale czy to tam gdzie kiedy cześć dziękuję proszę dzień dobry świat mężczyzna kobieta dziecko dom woda chleb tak dobrze",
}
_COMMON_SETS = {l: set(w.split()) for l, w in _COMMON.items()}


def _script_lang(text):
    """Definitive for non-Latin scripts via Unicode ranges."""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    kana = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
    hangul = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    arabic = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    deva = sum(1 for c in text if "\u0900" <= c <= "\u097f")
    beng = sum(1 for c in text if "\u0980" <= c <= "\u09ff")
    n = max(len(text), 1)
    if kana / n > 0.05:
        return "ja"
    if hangul / n > 0.05:
        return "ko"
    if cjk / n > 0.10:
        return "zh"
    if arabic / n > 0.10:
        return "ar"
    if deva / n > 0.10:
        return "hi"
    if beng / n > 0.10:
        return "bn"
    if cyrillic / n > 0.10:
        return "ru"
    return None


def detect_lang(text):
    """Return ISO-639-1 code or None. Offline-capable."""
    t = (text or "").strip().lower()
    if not t:
        return None
    sl = _script_lang(t)
    if sl:
        return sl
    words = re.findall(r"[a-zà-ÿâêîôûäöüßçñ]{2,}", t)
    if not words:
        return None
    scores = {}
    for lang, common in _COMMON_SETS.items():
        scores[lang] = sum(1 for w in words if w in common)
    best = max(scores, key=scores.get)
    # need a clear signal; short text gets a break (1 hit is a hint)
    ranked = sorted(scores.values(), reverse=True)
    nwords = len(words)
    if ranked[0] >= 2 and ranked[0] > ranked[1]:
        return best
    if nwords <= 12 and ranked[0] == 1 and ranked[1] == 0:
        return best
    return None


# --- local ONNX translation -----------------------------------------------
# Xenova's ONNX exports of Helsinki-NLP opus-mt. Quantized variants keep each
# pair around ~110 MB. Pairs without a dedicated model fall back to mul-en.
_PAIR_FALLBACK = {"pt": "mul", "hi": "mul", "bn": "mul"}
_HF = "https://huggingface.co"
_PAIR_FILES = (
    "onnx/encoder_model_quantized.onnx",
    "onnx/decoder_model_quantized.onnx",
    "tokenizer.json",
    "config.json",
    "generation_config.json",
)

_lock = threading.Lock()
_sessions = {}  # pair -> _PairMT
_dl_progress = {}  # pair -> {"file": str, "done": int, "total": int|None}


def download_progress():
    """Snapshot of any in-flight translation-pack downloads.

    Returns {pair: {"file", "done", "total"}} — empty dict when idle.
    Polled by the UI so a first-use pack download shows real progress
    instead of a frozen loading state.
    """
    with _lock:
        return {p: dict(s) for p, s in _dl_progress.items()}


def _pair_dir(data_dir, pair):
    d = os.path.join(data_dir or ".", "mt_models", pair)
    os.makedirs(d, exist_ok=True)
    return d


def _download(url, dest, timeout=_DL_TIMEOUT, progress=None):
    """Download a file, optionally reporting progress.

    Interrupted downloads resume: bytes already sitting in
    `<dest>.part` are continued with an HTTP Range request instead of
    being restarted from zero. If the server ignores the Range request,
    the partial file is discarded and the download restarts cleanly.
    The file only appears at `dest` once the download completes.

    progress(done_bytes, total_bytes_or_None) is called before the first
    chunk and after every chunk so the UI can show bytes downloaded.
    """
    part = dest + ".part"
    start = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = {"User-Agent": "Mozilla/5.0"}
    if start:
        headers["Range"] = "bytes=%d-" % start
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as e:
        # 416 = our partial file is already the whole file - done.
        if start and e.code == 416:
            os.replace(part, dest)
            if progress:
                progress(start, start)
            return
        raise
    with r, open(part, "ab" if start else "wb") as f:
        status = getattr(r, "status", 200)
        resumed = bool(start) and status == 206
        if start and not resumed:
            # Server ignored the Range request - start over.
            f.truncate(0)
            start = 0
        try:
            if resumed:
                # Content-Range looks like "bytes 100-199/1000".
                total = int(r.headers.get("Content-Range", "").rsplit("/", 1)[1])
            else:
                total = int(r.headers.get("Content-Length") or 0)
            total = total or None
        except (TypeError, ValueError, IndexError):
            total = None
        done = start
        if progress:
            progress(done, total)
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(part, dest)


def _ensure_pair(pair, data_dir):
    """Download + cache one translation pair. Returns dir or raises."""
    repo = f"Xenova/opus-mt-{pair}-en"
    d = _pair_dir(data_dir, pair)
    names = {
        "onnx/encoder_model_quantized.onnx": "encoder.onnx",
        "onnx/decoder_model_quantized.onnx": "decoder.onnx",
        "tokenizer.json": "tokenizer.json",
        "config.json": "config.json",
        "generation_config.json": "generation_config.json",
    }
    for remote, local in names.items():
        dest = os.path.join(d, local)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            continue

        def _report(done, total, _pair=pair, _local=local):
            with _lock:
                _dl_progress[_pair] = {"file": _local, "done": done,
                                       "total": total}

        try:
            _download(f"{_HF}/{repo}/resolve/main/{remote}", dest,
                      progress=_report)
        finally:
            with _lock:
                _dl_progress.pop(pair, None)
    # Xenova's tokenizer.json ships a null precompiled normalizer that the
    # Rust tokenizers loader rejects - drop it once at download time.
    tj = os.path.join(d, "tokenizer.json")
    try:
        with open(tj, encoding="utf-8") as f:
            td = json.load(f)
        norm = td.get("normalizer")
        if isinstance(norm, dict) and norm.get("precompiled_charsmap") is None:
            td["normalizer"] = None
            with open(tj, "w", encoding="utf-8") as f:
                json.dump(td, f)
    except Exception:
        pass
    for local in names.values():
        p = os.path.join(d, local)
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            raise RuntimeError(f"pair file missing: {local}")
    return d


class _PairMT:
    def __init__(self, directory):
        import numpy as _np  # noqa: F401  (kept local; cheap)
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self._np = _np
        self.tok = Tokenizer.from_file(os.path.join(directory, "tokenizer.json"))
        with open(os.path.join(directory, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        with open(os.path.join(directory, "generation_config.json"), encoding="utf-8") as f:
            gen = json.load(f)
        self.pad_id = cfg["pad_token_id"]
        self.eos_id = cfg["eos_token_id"]
        self.dec_start = gen.get("decoder_start_token_id", self.pad_id)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.enc = ort.InferenceSession(
            os.path.join(directory, "encoder.onnx"), sess_options=so,
            providers=["CPUExecutionProvider"])
        self.dec = ort.InferenceSession(
            os.path.join(directory, "decoder.onnx"), sess_options=so,
            providers=["CPUExecutionProvider"])

    def _split(self, text):
        """Split into ~400-token chunks on sentence boundaries."""
        sents = re.split(r"(?<=[.!?\n])\s+", text)
        chunks, cur, cur_n = [], [], 0
        for s in sents:
            n = len(self.tok.encode(s).ids) or 1
            if cur and cur_n + n > _CHUNK_TOKENS:
                chunks.append(" ".join(cur))
                cur, cur_n = [], 0
            cur.append(s)
            cur_n += n
        if cur:
            chunks.append(" ".join(cur))
        return [c for c in chunks if c.strip()] or [text]

    def translate(self, text):
        np = self._np
        out_chunks = []
        for ch in self._split(text):
            e = self.tok.encode(ch)
            ids = e.ids[:512] or [self.pad_id]
            ids_np = np.array([ids], dtype=np.int64)
            mask_np = np.array([[1] * len(ids)], dtype=np.int64)
            hs = self.enc.run(
                ["last_hidden_state"],
                {"input_ids": ids_np, "attention_mask": mask_np})[0]
            out_ids = [self.dec_start]
            max_new = min(512, len(ids) * 2 + 20)
            for _ in range(max_new):
                d_np = np.array([out_ids], dtype=np.int64)
                logits = self.dec.run(
                    ["logits"],
                    {"input_ids": d_np,
                     "encoder_attention_mask": mask_np,
                     "encoder_hidden_states": hs.astype(np.float32)})[0]
                nxt = int(np.argmax(logits[0, -1]))
                if nxt == self.eos_id:
                    break
                out_ids.append(nxt)
            out_chunks.append(self.tok.decode(out_ids[1:], skip_special_tokens=True))
        return " ".join(out_chunks).strip()


def _get_pair_mt(pair, data_dir):
    with _lock:
        mt = _sessions.get(pair)
        if mt is None:
            directory = _ensure_pair(pair, data_dir)
            mt = _PairMT(directory)
            _sessions[pair] = mt
        return mt


# --- public API ------------------------------------------------------------
def translate_to_english(text, data_dir=None):
    """Translate any-language text to English, fully on-device.

    Returns {"ok": True, "text": ..., "src": "es"} or
            {"ok": True, "text": ..., "src": "en", "message": "already_english"} or
            {"ok": False, "message": "no_pair"|"error"|"empty"}.
    The language pair downloads once on first use (~110 MB per pair).
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "message": "empty"}
    src = detect_lang(text)
    if src == "en":
        return {"ok": True, "text": text, "src": "en",
                "message": "already_english"}
    pair = _PAIR_FALLBACK.get(src, src or "mul")
    try:
        mt = _get_pair_mt(pair, data_dir)
    except Exception:
        return {"ok": False, "message": "no_pair"}
    try:
        out = mt.translate(text)
    except Exception:
        return {"ok": False, "message": "error"}
    if not out or out.lower() == text.lower():
        return {"ok": True, "text": text, "src": src or "auto",
                "message": "already_english"}
    return {"ok": True, "text": out, "src": src or pair}


def pack_info(data_dir):
    """List cached translation packs as [{"pair": str, "bytes": int}]."""
    root = os.path.join(data_dir or ".", "mt_models")
    out = []
    if os.path.isdir(root):
        for pair in sorted(os.listdir(root)):
            d = os.path.join(root, pair)
            if not os.path.isdir(d):
                continue
            total = 0
            for base, _ds, files in os.walk(d):
                for fn in files:
                    try:
                        total += os.path.getsize(os.path.join(base, fn))
                    except OSError:
                        pass
            out.append({"pair": pair, "bytes": total})
    return out


def clear_packs(data_dir):
    """Delete all cached translation packs.

    Returns {"pairs": [...], "bytes": freed}. Loaded sessions are dropped
    too, so the next translation re-downloads its pair on demand.
    """
    packs = pack_info(data_dir)
    freed = sum(p["bytes"] for p in packs)
    shutil.rmtree(os.path.join(data_dir or ".", "mt_models"),
                  ignore_errors=True)
    with _lock:
        _sessions.clear()
    return {"pairs": [p["pair"] for p in packs], "bytes": freed}
