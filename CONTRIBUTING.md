# Contributing to DropIt

Thanks for pitching in! DropIt is a small, deliberately dependency-light
project — please keep it that way.

## Project layout

| Path | What it is |
|---|---|
| `src/dropit.py` | The whole server + web UI in one stdlib-only Python file |
| `src/app.py` | pywebview desktop shell (native window, tray icon, QR pairing) |
| `src/dropit_ai.py` / `src/dropit_mt.py` | Optional AI search + on-device translation |
| `src/stub.py` | Tiny stub downloader that fetches the real installer |
| `installer/` | Windows build: `build.bat`, the Inno Setup script, version stamping |
| `docs/` | `AI-SETUP.txt`, `INSTALLER.md` — the detailed build/setup notes |
| `assets/` | Icons (the droplet logo is fixed artwork — don't redesign it) |
| `tests/` | pytest suite, all offline |

## Run from source

The core needs nothing but Python 3:

```bash
python src/dropit.py
# options: python src/dropit.py --port 9000 --dir ./shared
```

Open the printed address on your phone (same WiFi required).

AI features (Ask tab, image transcription, translation) need one extra step:

```bash
pip install -r requirements.txt
```

They also need the model files in `ai_model/` (~170 MB). Those ship in the
release zips and are **not** in git (see `.gitignore`). Without them the app
still runs fine — the AI endpoints just report `needs_setup`.

## Tests

```bash
pytest tests/
```

New behavior should come with a test. Keep tests offline (no network):
fake `urlopen`/HTTP responses the way `tests/test_mt_progress.py` does.

## Web UI gotchas (read before touching `src/dropit.py`)

The entire web page lives in a Python string (`PAGE`). Three rules, all
learned the hard way:

1. **Double your backslashes.** `PAGE` is a non-raw triple-quoted string, so a
   single `\n` in your JS source becomes a real newline in the served page —
   a syntax error that stuck the whole app on "Loading…" once. Write `\\n`.
2. **Never use `\uXXXX` escapes for emoji in the JS.** Python turns them into
   lone surrogates and the page dies with an encoding error. Paste the literal
   emoji character instead.
3. **Check the interpreted page, not the source.** Extract the `<script>` block
   from the *evaluated* `PAGE` (via `ast`, reading the assignment's
   `.value.value`) and run `node --check` on that, then assert zero lone
   surrogates and a clean UTF-8 encode.

## Windows installer

On a Windows PC, from `installer/`:

```bat
build.bat
```

That builds `DropIt.exe` (PyInstaller), the full offline installer (needs
[Inno Setup 6](https://jrsoftware.org/isdl.php)), and the stub downloader.
The full story — including what to upload to each GitHub Release — is in
`docs/INSTALLER.md`.

## Android app (APK)

The Android source lives outside this repo. It builds with a manual toolchain
(`aapt2` → `kotlinc` → `d8` → `zipalign` → `apksigner`, JDK 17 on `PATH`) and
is signed with the project's release key so updates install over the old APK.
Two hard rules: the launcher icon stays transparent with no borders, and a
rebuild never ships under an already-used version/build number.

## Versioning

1. Bump `VERSION` in `src/dropit.py`.
2. Run `installer/make_version_files.py` to regenerate the stamped files
   (`file_version_info.txt`, `version.iss`).
3. Never ship two different binaries under one identical version number.

## Pull requests

- One focused change per PR, with a clear *what* and *why* in the description.
- Never commit binaries, zips, APKs, or exes — those ship via GitHub
  Releases, never in the repo.
- The maintainer reviews and merges everything; PRs should be reviewable
  on their own (a real test, a real fix, or a real doc — no filler).
