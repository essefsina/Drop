"""Unit tests for _PairMT._split — sentence-boundary chunking.

Uses a stub tokenizer (2 tokens per word) so the tests run without the
~110 MB translation models, onnxruntime, or network access.
"""
import pytest

from dropit_mt import _CHUNK_TOKENS, _PairMT


class _FakeEnc:
    def __init__(self, ids):
        self.ids = ids


class _FakeTokenizer:
    """Deterministic stand-in: every word counts as 2 tokens."""

    def encode(self, s):
        n = max(1, 2 * len(s.split()))
        return _FakeEnc(list(range(n)))


@pytest.fixture()
def mt():
    pair = object.__new__(_PairMT)  # skip __init__ (loads ONNX models)
    pair.tok = _FakeTokenizer()
    return pair


def _tokens(mt, text):
    return len(mt.tok.encode(text).ids)


def test_short_text_is_single_chunk(mt):
    text = "Hello world. This is a short note."
    chunks = mt._split(text)
    assert chunks == [text]


def test_long_text_splits_into_multiple_chunks(mt):
    sents = [f"This is sentence number {i} with a few extra words." for i in range(60)]
    chunks = mt._split(" ".join(sents))
    assert len(chunks) > 1


def test_chunks_stay_under_token_limit(mt):
    sents = [f"Sentence {i} carries enough words to fill the chunk budget." for i in range(80)]
    chunks = mt._split(" ".join(sents))
    for c in chunks:
        # each chunk is a whole number of sentences, each <= limit,
        # so no chunk may exceed the limit
        assert _tokens(mt, c) <= _CHUNK_TOKENS


def test_splits_only_on_sentence_boundaries(mt):
    sents = [f"Sentence {i} ends here." for i in range(80)]
    chunks = mt._split(" ".join(sents))
    assert len(chunks) > 1
    for c in chunks[:-1]:
        assert c.rstrip().endswith((".", "!", "?"))


def test_no_content_lost_across_chunks(mt):
    sents = [f"Sentence {i} has unique content." for i in range(60)]
    chunks = mt._split(" ".join(sents))
    for s in sents:
        assert any(s in c for c in chunks), f"lost sentence: {s}"


def test_empty_text_falls_back_to_original(mt):
    assert mt._split("") == [""]
    assert mt._split("   ") == ["   "]


def test_single_huge_sentence_stays_whole(mt):
    # one sentence can never be split further; must not loop or vanish
    text = "word " * 5000
    chunks = mt._split(text.strip())
    assert chunks == [text.strip()]
