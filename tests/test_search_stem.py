"""Unit tests for dropit_ai._stem — the crude English stemming that
lets AI search match a plural query against a singular filename
("screenshots" hits "screenshot") and vice versa.

These tests pin the pairs the search actually relies on, plus the
guard clauses (short words stay untouched) and idempotence: stemming
a stemmed word must not mangle it further.
"""
from dropit_ai import _stem

# (plural/query form, singular/filename form) — both must stem alike.
PAIRS = [
    ("screenshots", "screenshot"),
    ("stories", "story"),
    ("boxes", "box"),
    ("cats", "cat"),
    ("dogs", "dog"),
    ("watches", "watch"),
    ("photos", "photo"),
]


def test_plural_and_singular_stem_alike():
    for plural, singular in PAIRS:
        assert _stem(plural) == _stem(singular), plural


def test_ies_becomes_y():
    assert _stem("stories") == "story"
    assert _stem("families") == "family"


def test_es_suffix_is_stripped():
    assert _stem("boxes") == "box"
    assert _stem("watches") == "watch"


def test_plain_s_suffix_is_stripped():
    assert _stem("screenshots") == "screenshot"
    assert _stem("cats") == "cat"


def test_short_words_unchanged():
    # len <= 3 words never lose a trailing "s" ("bus", "gas").
    assert _stem("bus") == "bus"
    assert _stem("gas") == "gas"
    assert _stem("cat") == "cat"


def test_stemming_is_idempotent():
    for word in ["screenshots", "stories", "boxes", "screenshot", "story"]:
        assert _stem(_stem(word)) == _stem(word), word


def test_no_substring_matching():
    # Stemming is whole-word only: it must not equate unrelated words
    # that merely share letters (the search comment's "logo" vs
    # "catalogue" rule relies on this word-level behaviour).
    assert _stem("logo") != _stem("catalogue")
    assert _stem("cat") != _stem("catalogue")
