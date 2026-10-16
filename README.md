# 📲 DropIt

**Beam files from your phone to your PC over WiFi. No cloud, no accounts, no cables.**

DropIt turns your PC into a private file-drop server. Open the app, scan the QR code
with your phone, and send photos, videos, documents, or text — they land straight
in your shared folder. Everything stays on your local network.

## ✨ Features

- **Phone → PC file transfer** over your WiFi — photos, videos, any files
- **Shared Texts** — send snippets and notes between devices instantly
- **Ask DropIt** — AI file search: find files from plain-English prompts
  ("motorcycle pic", "email screenshot from last week")
- **Sees inside images** — on-device vision finds objects and scenes in your photos
- **Reads text in images** — OCR transcription, fully local
- **Translates on-device** — foreign text detected and translated to English,
  no cloud involved
- **Native desktop app** — system tray, QR pairing, start-with-Windows
- **Android app** — lightweight companion, same WiFi magic

## 🚀 Quickstart

**Easiest — Windows installer:**
Download `DropIt-Setup.exe` from the
[latest release](https://github.com/essefsina/DropIt/releases/latest),
run it, done.

**From source:**

```bash
git clone https://github.com/essefsina/DropIt.git
cd DropIt
pip install -r requirements.txt
python src/dropit.py        # web UI (any browser)
# or
python src/app.py           # native desktop window
```

Then on your phone, open the QR code shown and start sending.

## 🧠 The AI part (100% local)

Ask DropIt runs entirely on your PC — no accounts, no API keys, no cloud:

| Capability | How |
|---|---|
| Semantic file search | Quantized MiniLM embeddings (`ai_model/`, ~23 MB) |
| Photo understanding | Quantized CLIP vision model (~150 MB) |
| Text in images | RapidOCR, on-device |
| Translation | ONNX opus-mt pairs, downloaded once per language (~110 MB) |

Translation packs download automatically the first time you translate from a
language, then work offline forever. See [docs/AI-SETUP.txt](docs/AI-SETUP.txt).

## 📁 Project layout

```
DropIt/
├── src/            # application source (dropit.py, app.py, dropit_ai.py, dropit_mt.py, stub.py)
├── installer/      # Inno Setup installer + build scripts (Windows)
├── docs/           # setup guides (INSTALLER.md, AI-SETUP.txt)
├── assets/         # icons and artwork
└── requirements.txt
```

## 🔨 Building the installer (Windows)

```cmd
cd installer
build.bat
```

Needs Python 3 and [Inno Setup 6](https://jrsoftware.org/isdl.php).
Outputs `DropIt-Setup.exe` — upload it to each GitHub Release.

## 📱 Android

The Android companion is built with a manual
`aapt2`/`kotlinc`/`d8` pipeline (no Gradle) — see the release APKs.

## 📄 License

MIT — see [LICENSE](LICENSE).
