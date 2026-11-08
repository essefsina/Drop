"""Tests for the --version CLI flag on dropit.py and app.py.

Both entry points must print the same "DropIt <version>" line and exit
cleanly, so a user (or a script) can check the installed version without
starting the server or opening a window.
"""

from __future__ import annotations

import os
import subprocess
import sys

import dropit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_version(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "src", script), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )


def test_dropit_version_flag():
    proc = _run_version("dropit.py")
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"DropIt {dropit.VERSION}"
    assert proc.stderr == ""


def test_app_version_flag_matches_server():
    proc = _run_version("app.py")
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"DropIt {dropit.VERSION}"


def test_version_output_is_a_single_line():
    proc = _run_version("dropit.py")
    assert proc.stdout.strip().count("\n") == 0
    assert proc.stdout.strip().startswith("DropIt ")
