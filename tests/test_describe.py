"""Unit tests for dropit_ai._describe — the single string the text
embedder sees for a file: the filename, normalised, plus the file's
text when there is any.

These tests pin the exact contract search relies on: underscores and
dashes become spaces, the extension is stripped, text is stripped and
capped at MAX_TEXT_CHARS, and a file with no usable text describes
itself by name alone.
"""
from dropit_ai import MAX_TEXT_CHARS, _describe


def test_name_only_when_text_empty():
    assert _describe("report.txt", "") == "report"
    assert _describe("report.txt", None) == "report"


def test_whitespace_only_text_is_ignored():
    assert _describe("notes.md", "   \n\t ") == "notes"


def test_underscores_and_dashes_become_spaces():
    assert _describe("my_vacation-photo.jpg", "x") == "my vacation photo. x"


def test_extension_stripped_only():
    # splitext strips the last suffix; inner dots stay part of the name.
    assert _describe("archive.tar.gz", "x") == "archive.tar. x"


def test_text_appended_after_dot_space():
    assert _describe("invoice.pdf", "amount due") == "invoice. amount due"


def test_text_is_stripped_before_appending():
    assert _describe("memo.txt", "  padded text\n") == "memo. padded text"


def test_text_capped_at_max_text_chars():
    long_text = "x" * (MAX_TEXT_CHARS + 500)
    result = _describe("big.txt", long_text)
    assert result == "big. " + "x" * MAX_TEXT_CHARS
    assert len(result) == len("big. ") + MAX_TEXT_CHARS


def test_text_exactly_at_cap_is_kept_whole():
    text = "y" * MAX_TEXT_CHARS
    assert _describe("exact.txt", text) == "exact. " + text
