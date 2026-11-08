#!/usr/bin/env python3
"""Drop desktop app - native window + system tray around the Drop server.

Run:
    python app.py
Build a Windows .exe:
    pip install -r requirements.txt
    pyinstaller --noconfirm --onefile --windowed --name DropIt --icon icon.ico --add-data "icon.png;." --add-data "logo.png;." --add-data "ai_model;ai_model" app.py
"""

import argparse
import json
import os
import subprocess
import sys
import threading

import dropit

VERSION = dropit.VERSION


# ------------------------------------------------------------ saved config
def _config_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "DropIt")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".config", "DropIt")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "config.json")


def load_config() -> dict:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


# ---------------------------------------------------------------- js api
def _spawn(argv):
    """Spawn a GUI helper (Explorer / Finder / xdg-open) from the
    frozen --windowed app.
    v2.8.20 (9): explicit DEVNULL stdio + close_fds. A windowed
    PyInstaller build has no console and no valid std handles;
    letting the child inherit them makes Popen raise
    [WinError 6] "The handle is invalid" on the PC -- which is
    why "Show in folder" was dead while open_folder/open_file
    (os.startfile on Windows) worked. The 2.8.18 probe could
    never see this: it faked Popen, on Linux. DEVNULL stdio
    removes the parent's handles from the child entirely."""
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            close_fds=True)
def _browse_for_folder_win(title="Choose a folder", initial=None):
    """Native Windows folder picker (SHBrowseForFolderW).

    pywebview's file dialog opens a *file* picker even with directory=True,
    so this calls the real Win32 folder browser instead. Runs its own modal
    loop, so it works from any thread. Returns the path or None on cancel.
    """
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    user32 = ctypes.windll.user32

    BIF_RETURNONLYFSDIRS = 0x0001
    BIF_NEWDIALOGSTYLE = 0x0040
    BFFM_INITIALIZED = 1
    BFFM_SETSELECTIONW = 0x467  # WM_USER + 103

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", ctypes.c_uint),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    init_path = os.path.abspath(os.path.expanduser(initial)) if initial else None

    @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, ctypes.c_uint,
                        wintypes.LPARAM, wintypes.LPARAM)
    def _cb(hwnd, msg, lp, data):
        if msg == BFFM_INITIALIZED and init_path:
            user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1, init_path)
        return 0

    user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                    wintypes.WPARAM, wintypes.LPCWSTR]
    user32.SendMessageW.restype = wintypes.LPARAM
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    # NOTE: every one of these needs explicit argtypes. Without them ctypes
    # defaults to c_int, which cannot hold a 64-bit pointer/address and dies
    # with "OverflowError: int too long to convert".
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long  # HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    # The new-style folder dialog needs COM on this thread. pywebview's
    # JS bridge may call us from a thread where COM isn't initialized,
    # which makes the dialog fail outright.
    COINIT_APARTMENTTHREADED = 0x2
    com_ok = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        display = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        bi = BROWSEINFOW()
        bi.hwndOwner = None
        bi.pidlRoot = None
        bi.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
        bi.lpszTitle = title
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        bi.lpfn = ctypes.cast(_cb, ctypes.c_void_p)
        bi.lParam = 0
        bi.iImage = 0

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None
        try:
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if shell32.SHGetPathFromIDListW(pidl, buf):
                return buf.value or None
            return None
        finally:
            ole32.CoTaskMemFree(pidl)
            _cb  # keep the callback alive until the dialog is gone  # noqa: B018
    finally:
        if com_ok == 0:  # S_OK: we initialized COM, so uninitialize it
            ole32.CoUninitialize()


class Api:
    """Exposed to the web UI as window.pywebview.api."""

    def __init__(self, server):
        self.server = server
        # v2.8.31 custom title bar: set by main() once the window
        # is created (True only when frameless creation worked).
        self.frameless = False
        self._maximized = False

    def _window(self):
        """The pywebview window, or None (no window / webview missing)."""
        try:
            import webview

            wins = getattr(webview, "windows", [])
            return wins[0] if wins else None
        except Exception:  # noqa: BLE001
            return None

    def is_frameless(self) -> dict:
        """v2.8.31: True when the window was created frameless, so the
        page knows whether to show its own title bar. A framed
        fallback window keeps the native bar and the page hides
        the custom one."""
        return {"ok": True, "frameless": bool(getattr(self, "frameless", False))}

    def is_maximized(self) -> dict:
        """v2.8.31: maximise state for the title-bar icon (maximise
        square vs restore overlapping-squares). Falls back to the
        toggle-tracked flag when the platform window exposes none."""
        win = self._window()
        state = None
        if win is not None:
            state = getattr(win, "is_maximized", None)
        if state is None:
            state = bool(getattr(self, "_maximized", False))
        return {"ok": True, "maximized": bool(state)}

    def minimize_window(self) -> dict:
        """v2.8.31: title-bar minimise. The existing minimized event
        still fires, so minimise-to-tray behaviour is unchanged."""
        win = self._window()
        if win is None:
            return {"ok": False, "error": "no window"}
        try:
            win.minimize()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def toggle_maximize_window(self) -> dict:
        """v2.8.31: title-bar maximise / restore toggle."""
        win = self._window()
        if win is None:
            return {"ok": False, "error": "no window"}
        try:
            if self.is_maximized()["maximized"]:
                win.restore()
                self._maximized = False
            else:
                win.maximize()
                self._maximized = True
            return {"ok": True, "maximized": bool(self._maximized)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def close_window(self) -> dict:
        """v2.8.31: title-bar close -- destroys the window, which
        ends webview.start() and exits the app, as X does today."""
        win = self._window()
        if win is None:
            return {"ok": False, "error": "no window"}
        try:
            win.destroy()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def move_window(self, x, y) -> dict:
        """v2.8.31: move the window's top-left corner to (x, y)
        screen pixels -- the title-bar drag path. A window whose
        platform backend has no move verb reports it and the
        window simply stays put; it is never left unusable."""
        win = self._window()
        if win is None:
            return {"ok": False, "error": "no window"}
        try:
            move = getattr(win, "move", None)
            if move is None:
                return {"ok": False, "error": "move not supported"}
            move(int(x), int(y))
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def _link_dir(self) -> str:
        """The CURRENT link's folder (v2.7.84), not the base root.
        v2.7.83 opened server.directory here, so Open folder opened
        the shared root even when files lived in base/<link>/, and
        Open file looked for link files in the root and failed.
        v2.7.96 FIX: this used to call dropit._link_folder, which
        does not exist -- the AttributeError fell through to the
        root fallback, so every bridge Open folder opened the
        ROOT, not the address folder. It now calls the real
        dropit._address_folder. The MENU's root route does not
        use this at all; it uses open_root_folder() below."""
        try:
            cfg = dropit._load_config()
            d = dropit._address_folder(cfg)
            if d:
                return d
        except Exception:  # noqa: BLE001
            pass
        return self.server.directory

    def host_token(self) -> str:
        """Desktop host proof (v2.7.88). Returns the server's
        in-memory host token to the pywebview window's own page
        ONLY, via this local JS bridge. No LAN browser has this
        bridge, so no guest can call this. The page keeps the token
        in JS memory only (never localStorage, never a URL) and
        sends it as X-Drop-Host, which lets the desktop window be
        recognised as host even if its page was loaded via a LAN IP
        or .local name instead of loopback."""
        try:
            return str(getattr(self.server, "host_token", "") or "")
        except Exception:  # noqa: BLE001
            return ""

    def open_root_folder(self) -> bool:
        """Open the ROOT folder (v2.7.96 MENU route), not the
        current address's subfolder. The menu's Open folder
        targets this; the Files tab / Set Up dialog use
        open_folder() (address folder) instead."""
        folder = self.server.directory
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                _spawn(["open", folder])
            else:
                _spawn(["xdg-open", folder])
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_root_directory(self, path: str) -> dict:
        """Change the ROOT folder only (v2.7.96 MENU route):
        cfg["directory"] + server.directory, with per-address
        folder overrides left untouched. Unlike set_directory(),
        a link being active does NOT redirect this into that
        link's override."""
        try:
            raw = str(path).strip().strip('"')
            if not raw:
                return {"ok": False, "error": "empty path"}
            new = os.path.abspath(os.path.expanduser(raw))
            if sys.platform == "win32":
                drive = os.path.splitdrive(new)[0]
                if drive and not os.path.isdir(drive + os.sep):
                    return {"ok": False, "error": f"drive {drive} not found"}
            os.makedirs(new, exist_ok=True)
            cfg = load_config()
            cfg["directory"] = new
            self.server.directory = new
            save_config(cfg)
            return {"ok": True, "directory": new, "dirname": os.path.basename(new)}
        except OSError as e:
            return {"ok": False, "error": str(e)}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "unexpected error"}

    def browse_root_directory(self) -> dict:
        """Pick the ROOT folder with a native folder dialog
        (v2.7.96 MENU route), then set_root_directory()."""
        if sys.platform == "win32":
            try:
                path = _browse_for_folder_win(
                    title="Choose the Drop root folder",
                    initial=self.server.directory,
                )
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                return {"ok": False,
                        "error": "Folder picker failed (%s: %s)"
                                 % (type(e).__name__, e)}
            if not path:
                return {"ok": False, "error": "cancelled"}
            try:
                return self.set_root_directory(path)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        try:
            import webview

            wins = getattr(webview, "windows", [])
            if not wins:
                return {"ok": False, "error": "no window"}
            result = wins[0].create_file_dialog(
                webview.OPEN_DIALOG,
                directory=True,
                allow_multiple=False,
            )
            if not result:
                return {"ok": False, "error": "cancelled"}
            path = result[0] if isinstance(result, (list, tuple)) else result
            return self.set_root_directory(path)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def open_folder(self) -> bool:
        folder = self._link_dir()
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                _spawn(["open", folder])
            else:
                _spawn(["xdg-open", folder])
            return True
        except Exception:  # noqa: BLE001
            return False

    def open_file(self, name: str) -> bool:
        """Open a file in the save folder with its default app."""
        try:
            base = self._link_dir()
            clean = dropit.safe_name(name)
            path = os.path.abspath(os.path.join(base, clean))
            if not path.startswith(os.path.abspath(base) + os.sep):
                return False
            if not os.path.isfile(path):
                return False
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                _spawn(["open", path])
            else:
                _spawn(["xdg-open", path])
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_last_reveal(self) -> dict:
        """v2.8.20 (9): the last reveal_file attempt, read back by
        the page (revealFile asks this when the bridge says no,
        and names the recorded error in its toast). The frozen
        windowed build has nowhere to print stderr, so without
        this a failed reveal is invisible on the PC."""
        try:
            rec = getattr(self, "last_reveal", None)
            return dict(rec) if isinstance(rec, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def reveal_file(self, name: str) -> bool:
        """v2.8.9: open the save folder with this file selected /
        highlighted (the per-file Open button's new job), instead
        of opening the file itself. Windows: Explorer /select;
        macOS: Finder -R. Linux has no select verb, so it opens
        the folder itself. Same path jailing as open_file.
        v2.8.17: the Explorer call MUST be the two-item list
        ["explorer", "/select," + path]. The 2.8.14 verbatim
        string was EXACTLY the bug: CPython's Windows
        _execute_child runs list2cmdline([args]) when args is
        a str, so the whole `explorer /select,"C:\\..."`
        command gets outer-quoted as ONE token and
        CreateProcess cannot find the program (the 2.8.14
        in-process test only captured the string passed to
        Popen, never the real command line). With the list
        form, list2cmdline produces `explorer
        /select,C:\\...` -- the switch and path stay one
        argument, quoted only when the path has spaces,
        which Explorer parses. Do NOT use the three-item
        form ["explorer", "/select,", path] (the 2.8.11 bug:
        a space after the comma = an empty path to select).
        The same fix is in the server /api/reveal handler.
        v2.8.18: every attempt is recorded on self.last_reveal
        (name / resolved path / argv / ok / error) and failures
        are logged to stderr, so a "nothing happens" click on
        the PC leaves proof of whether the bridge was reached,
        whether the file was found, and what Explorer was
        asked to run -- instead of dying silently.
        v2.8.20 (9): the ROOT CAUSE, found by comparing the
        spawn sites -- reveal_file is the ONLY Windows path in
        the app that uses subprocess.Popen; open_folder,
        open_file and open_root_folder all use os.startfile on
        Windows (and they work). In the frozen --windowed
        build the process has no console and no valid std
        handles, so Popen's inherited stdio fails the spawn
        with [WinError 6] "The handle is invalid" -- caught
        here, recorded, and returned as False, which is why
        the click died with nothing visibly happening (the
        2.8.18 probe faked Popen on Linux, so it could never
        see this). The spawn now goes through _spawn()
        (DEVNULL stdio + close_fds), and get_last_reveal()
        lets the page read the record back."""
        self.last_reveal = {"name": name, "ok": False, "error": "",
                            "path": "", "argv": None}
        try:
            base = self._link_dir()
            clean = dropit.safe_name(name)
            path = os.path.abspath(os.path.join(base, clean))
            self.last_reveal["path"] = path
            if not path.startswith(os.path.abspath(base) + os.sep):
                self.last_reveal["error"] = "path outside save folder"
                return False
            if not os.path.isfile(path):
                self.last_reveal["error"] = "file not found: " + path
                print("[Drop] reveal_file: file not found: %s"
                      % path, file=sys.stderr, flush=True)
                return False
            if sys.platform == "win32":
                argv = ["explorer", "/select," + path]
                self.last_reveal["argv"] = argv
                _spawn(argv)
            elif sys.platform == "darwin":
                argv = ["open", "-R", path]
                self.last_reveal["argv"] = argv
                _spawn(argv)
            else:
                argv = ["xdg-open", base]
                self.last_reveal["argv"] = argv
                _spawn(argv)
            self.last_reveal["ok"] = True
            return True
        except Exception as e:  # noqa: BLE001
            self.last_reveal["error"] = "%s: %s" % (type(e).__name__, e)
            print("[Drop] reveal_file failed for %r: %s: %s"
                  % (name, type(e).__name__, e), file=sys.stderr,
                  flush=True)
            return False

    def open_path(self, path: str) -> bool:
        """Open an arbitrary local file (e.g. a note the user saved via Save dialog)."""
        try:
            p = os.path.abspath(os.path.expanduser(str(path)))
            if not os.path.isfile(p):
                return False
            if sys.platform == "win32":
                os.startfile(p)  # noqa: S606
            elif sys.platform == "darwin":
                _spawn(["open", p])
            else:
                _spawn(["xdg-open", p])
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_directory(self, path: str) -> dict:
        """Change the save folder from the web UI. Returns JSON-serializable.
        v2.7.84: with a link active this changes THAT link's folder
        (its registry override) and leaves the base root untouched, so
        switching links later still finds each link's own folder. With
        no link it moves the base root, as before."""
        try:
            raw = str(path).strip().strip('"')
            if not raw:
                return {"ok": False, "error": "empty path"}
            new = os.path.abspath(os.path.expanduser(raw))
            if sys.platform == "win32":
                drive = os.path.splitdrive(new)[0]
                if drive and not os.path.isdir(drive + os.sep):
                    return {"ok": False, "error": f"drive {drive} not found"}
            os.makedirs(new, exist_ok=True)
            cfg = load_config()
            link = dropit._current_address(cfg)
            if link:
                entry = dropit._address_entry(cfg, link)
                entry["folder"] = new
            else:
                cfg["directory"] = new
                self.server.directory = new
            save_config(cfg)
            return {"ok": True, "directory": new, "dirname": os.path.basename(new)}
        except OSError as e:
            return {"ok": False, "error": str(e)}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "unexpected error"}

    def browse_directory(self) -> dict:
        """Let the user pick the save folder with a native folder dialog."""
        if sys.platform == "win32":
            # Real folder picker. pywebview's dialog opens a *file* picker
            # even with directory=True, so it is not used here on Windows.
            try:
                path = _browse_for_folder_win(
                    title="Choose the Drop save folder",
                    initial=self._link_dir(),
                )
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                return {"ok": False,
                        "error": "Folder picker failed (%s: %s)"
                                 % (type(e).__name__, e)}
            if not path:
                return {"ok": False, "error": "cancelled"}
            try:
                return self.set_directory(path)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        try:
            import webview

            wins = getattr(webview, "windows", [])
            if not wins:
                return {"ok": False, "error": "no window"}
            result = wins[0].create_file_dialog(
                webview.OPEN_DIALOG,
                directory=True,
                allow_multiple=False,
            )
            if not result:
                return {"ok": False, "error": "cancelled"}
            path = result[0] if isinstance(result, (list, tuple)) else result
            return self.set_directory(path)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def save_note(self, params) -> dict:
        """Save a text note through a native save dialog (desktop window)."""
        try:
            import webview

            text = str(params.get("text", "")) if isinstance(params, dict) else ""
            nid = str(params.get("id", "note")) if isinstance(params, dict) else "note"
            wins = getattr(webview, "windows", [])
            if not wins:
                return {"ok": False, "error": "no window"}
            safe = "".join(c for c in nid if c.isalnum())[:32] or "note"
            result = wins[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename="shared-text-%s.txt" % safe,
                file_types=("Text files (*.txt)",),
            )
            if not result:
                return {"ok": False, "error": "cancelled"}
            path = result[0] if isinstance(result, (list, tuple)) else result
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return {"ok": True, "path": path}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def get_clipboard(self) -> dict:
        """Read text from the native clipboard (no browser permission prompt)."""
        try:
            import tkinter

            r = tkinter.Tk()
            r.withdraw()
            try:
                text = r.clipboard_get()
            except Exception:  # noqa: BLE001
                text = ""  # empty or non-text clipboard
            r.destroy()
            return {"ok": True, "text": text or ""}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "text": "", "error": str(e)}


# --------------------------------------------------------------- tray icon
def _tray_image():
    from PIL import Image

    real = dropit.asset_path("icon.png")
    if real:
        try:
            img = Image.open(real).convert("RGBA")
            img.thumbnail((64, 64), Image.LANCZOS)
            return img
        except Exception:  # noqa: BLE001
            pass
    # fallback: generated arrow icon
    from PIL import ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, size - 4, size - 4], radius=14, fill=(56, 189, 248, 255))
    # down arrow into tray
    d.rectangle([size // 2 - 5, 14, size // 2 + 5, 38], fill="white")
    d.polygon(
        [(size // 2 - 13, 36), (size // 2 + 13, 36), (size // 2, 50)],
        fill="white",
    )
    d.rectangle([16, 50, size - 16, 55], fill="white")
    return img


def copy_text(text: str) -> None:
    try:
        import tkinter

        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------- autostart
def _run_key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_READ | winreg.KEY_SET_VALUE,
    )


def is_autostart() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with _run_key() as k:
            winreg.QueryValueEx(k, "DropIt")
        return True
    except OSError:
        return False


def set_autostart(enable: bool) -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        with _run_key() as k:
            import winreg

            if enable:
                # --minimized: start hidden in the tray, no window popup on boot
                winreg.SetValueEx(
                    k, "DropIt", 0, winreg.REG_SZ, f'"{sys.executable}" --minimized'
                )
            else:
                try:
                    winreg.DeleteValue(k, "DropIt")
                except OSError:
                    pass
    except OSError:
        pass


def start_tray(server, window=None):
    """Best-effort system tray; the app works fine without it. Returns the icon."""
    try:
        import pystray
    except ImportError:
        return None

    def on_open(icon, item):
        try:
            if window is not None:
                window.show()
                window.restore()
        except Exception:  # noqa: BLE001
            pass

    def on_copy(icon, item):
        # v2.8.29 (3): the tray copies the FULL WORKING URL -- the
        # SAME http://<LAN IP>:<port>/ the QR code encodes -- so
        # pasting it into a browser opens the web version. The
        # bare link name / .local form cannot be resolved by most
        # phone browsers (see dropit.fullAddressUrl).
        try:
            copy_text(dropit._qr_connect_url(server))
        except Exception:  # noqa: BLE001
            pass

    def on_autostart(icon, item):
        set_autostart(not is_autostart())

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open Drop", on_open, default=True),
        pystray.MenuItem("Copy phone link", on_copy),
        pystray.MenuItem(
            "Start with Windows",
            on_autostart,
            checked=lambda item: is_autostart(),
            enabled=sys.platform == "win32" and getattr(sys, "frozen", False),
        ),
        pystray.MenuItem("Quit Drop", on_quit),
    )
    try:
        icon = pystray.Icon("DropIt", _tray_image(), f"Drop - {server.url}", menu)
        icon.run_detached()
        return icon
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Drop desktop app")
    ap.add_argument("--version", action="version", version=f"Drop {VERSION}")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default=None,
                    help="Save folder (overrides the remembered one)")
    ap.add_argument("--minimized", action="store_true",
                    help="Start hidden in the system tray")
    args = ap.parse_args()

    cfg = load_config()
    directory = (
        args.dir
        or cfg.get("directory")
        or os.path.join(os.path.expanduser("~"), "DropIt")
    )

    server = dropit.make_server(args.port, directory, desktop=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Drop {VERSION} - {server.url} -> {server.directory}")
    # v2.8.41 (1): warm the AI index in the background at startup,
    # like dropit.py main() does -- the desktop app never did, so
    # the first search after a restart WAS the full index build
    # (past the 75s timeout on real photo folders). Never breaks
    # startup: _preload_ai catches its own errors.
    threading.Thread(target=dropit._preload_ai, args=(server.directory,),
                     daemon=True).start()

    try:
        import webview
    except ImportError:
        print("pywebview not installed - opening in browser instead.")
        print("Install the desktop shell with: pip install -r requirements.txt")
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return

    # v2.8.31 custom themed title bar (PC app only): the window goes
    # FRAMELESS and Drop draws its own bar (logo + Drop left, custom
    # minimise / maximise / close right -- see the #titlebar in
    # dropit.py). Fallback safety: if this pywebview cannot do
    # frameless, open a normal FRAMED window instead -- never a
    # dead window with no way to close or move it. The page asks
    # the bridge (is_frameless) and hides its custom bar when the
    # fallback ran, so the native bar is the chrome then.
    api = Api(server)
    try:
        # v2.8.34 (5): easy_drag=False -- pywebview's easy-drag
        # mode (the DEFAULT for frameless windows) lets the
        # window be moved by dragging ANY point, which is why
        # click-and-hold anywhere -- including selecting text
        # in a text preview -- moved the app, and why it
        # jumped on clicks (the native easy-drag and the JS
        # title-bar drag below fought over the same move).
        # With easy_drag off, the ONLY drag path is the JS
        # title-bar handler in dropit.py (mousedown on
        # #titlebar -> move_window), so clicks, holds and
        # text selection anywhere else never move the window.
        window = webview.create_window(
            "Drop",
            f"http://127.0.0.1:{args.port}",
            width=1280,
            height=800,
            min_size=(720, 600),
            js_api=api,
            hidden=args.minimized,
            frameless=True,
            easy_drag=False,
        )
        api.frameless = True
    except Exception:  # noqa: BLE001
        window = webview.create_window(
            "Drop",
            f"http://127.0.0.1:{args.port}",
            width=1280,
            height=800,
            min_size=(720, 600),
            js_api=api,
            hidden=args.minimized,
        )
        api.frameless = False

    start_tray(server, window)

    # Minimize-to-tray: the minimize button hides the window to the tray.
    # Closing (X) exits the app for real. Reopen from the tray (double-click
    # it or choose Open Drop); quit from the tray menu.
    def on_minimized():
        try:
            window.hide()
        except Exception:  # noqa: BLE001
            pass

    try:
        window.events.minimized += on_minimized
    except Exception:  # noqa: BLE001
        pass

    webview.start()
    os._exit(0)


if __name__ == "__main__":
    main()
