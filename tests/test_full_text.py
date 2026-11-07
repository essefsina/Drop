"""Unit tests for dropit_ai.full_text — the complete readable text for
one file, used by the transcribe path.

Unlike extract_text (capped at MAX_TEXT_CHARS for the search index),
full_text returns the whole document with paragraph breaks preserved,
up to its own 500k-char guard. Anything it cannot read returns ""
instead of raising: transcription must never crash on one bad file.
"""
from dropit_ai import full_text


def test_plain_text_file_returned_in_full(tmp_path):
    path = tmp_path / "notes.txt"
    text = "first paragraph\n\nsecond paragraph\nthird line"
    path.write_text(text, encoding="utf-8")
    assert full_text(str(path)) == text


def test_markdown_and_code_files_are_text(tmp_path):
    md = tmp_path / "readme.md"
    md.write_text("# Title\nsome notes", encoding="utf-8")
    assert full_text(str(md)) == "# Title\nsome notes"
    py = tmp_path / "script.py"
    py.write_text("print('hello')\n", encoding="utf-8")
    assert full_text(str(py)) == "print('hello')\n"


def test_long_text_file_not_capped_like_extract_text(tmp_path):
    # full_text has no MAX_TEXT_CHARS cap: a 5000-char file comes back
    # whole, where extract_text would truncate it.
    path = tmp_path / "big.txt"
    path.write_text("x" * 5000, encoding="utf-8")
    assert full_text(str(path)) == "x" * 5000


def test_unknown_extension_returns_empty(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"\x00\x01\x02\x03")
    assert full_text(str(path)) == ""


def test_missing_file_returns_empty_without_raising(tmp_path):
    assert full_text(str(tmp_path / "nope.txt")) == ""


def test_empty_file_returns_empty(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    assert full_text(str(path)) == ""


def test_unreadable_pdf_returns_empty(tmp_path):
    # Not a real PDF: PdfReader raises (or is missing) and full_text
    # must still return "" instead of propagating the error.
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf at all")
    assert full_text(str(path)) == ""
