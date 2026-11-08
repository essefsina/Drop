"""Unit tests for dropit_ai.extract_text — the best-effort text
extractor behind AI search indexing.

Plain-text files are read in full, while anything it cannot read
(unknown extension, missing file) returns "" instead of raising:
indexing must never crash on one bad file. Long files are capped at
MAX_TEXT_CHARS so a single huge file cannot blow up the index.
"""
from dropit_ai import MAX_TEXT_CHARS, extract_text


def test_plain_text_file_read_fully(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world\nsecond line", encoding="utf-8")
    assert extract_text(str(path)) == "hello world\nsecond line"


def test_markdown_and_code_files_are_text(tmp_path):
    md = tmp_path / "readme.md"
    md.write_text("# Title\nsome notes", encoding="utf-8")
    assert extract_text(str(md)) == "# Title\nsome notes"
    py = tmp_path / "script.py"
    py.write_text("print('hello')\n", encoding="utf-8")
    assert extract_text(str(py)) == "print('hello')\n"


def test_unknown_extension_returns_empty(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"\x00\x01\x02\x03")
    assert extract_text(str(path)) == ""


def test_missing_file_returns_empty_without_raising(tmp_path):
    assert extract_text(str(tmp_path / "nope.txt")) == ""


def test_long_file_is_capped_at_max_text_chars(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 5000, encoding="utf-8")
    result = extract_text(str(path))
    assert len(result) == MAX_TEXT_CHARS
    assert result == "x" * MAX_TEXT_CHARS
