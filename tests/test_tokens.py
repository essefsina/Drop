"""Unit tests for dropit_ai._tokens.

_tokens feeds the keyword search: stemmed latin words plus CJK runs
and their bigrams (CJK has no word spaces, so bigrams are the closest
thing to keywords). No AI models needed — pure string handling.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dropit_ai  # noqa: E402
from dropit_ai import _tokens  # noqa: E402


def test_lowercases_and_stems_latin_words():
    assert _tokens("Screenshots PHOTOS") == {"screenshot", "photo"}


def test_stems_ies_and_es_endings():
    assert _tokens("cities classes") == {"city", "class"}


def test_splits_on_punctuation_and_underscores():
    assert _tokens("don't stop: my_file.txt") == {
        "don", "t", "stop", "my", "file", "txt",
    }


def test_keeps_digits_with_words():
    assert _tokens("abc123 2024 report") == {"abc123", "2024", "report"}


def test_deduplicates_repeated_words():
    assert _tokens("beach beach BEACH") == {"beach"}


def test_empty_and_none_give_empty_set():
    assert _tokens("") == set()
    assert _tokens(None) == set()


def test_whitespace_only_gives_empty_set():
    assert _tokens("   \n\t") == set()


def test_cjk_run_and_its_bigrams():
    assert _tokens("你好世界") == {"你好世界", "你好", "好世", "世界"}


def test_single_cjk_character_has_no_bigrams():
    assert _tokens("日") == {"日"}


def test_mixed_latin_and_cjk():
    assert _tokens("hello 你好") == {"hello", "你好"}


def test_cjk_run_split_by_space_gives_separate_runs():
    assert _tokens("你好 世界") == {"你好", "世界"}


def test_short_words_unchanged():
    # _stem leaves words of length <= 3 alone, and "is"/"as" stay as-is.
    assert _tokens("is as at an ox") == {"is", "as", "at", "an", "ox"}
