"""Search precision regression tests (v2.7.83 revert + fix build).

Covers the user-reported failures:
  - garbage keyword -> zero results
  - a word literally in a picture / long document -> that file, and
    only genuinely matching files (no CLIP/embedding tail)
  - a classification word -> the matching photos, no unrelated items

Skipped when the bundled AI models are not present (model_ready False),
so the suite stays green on machines without ai_model/.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dropit_ai  # noqa: E402


def _font(sz):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    if not dropit_ai.model_ready():
        pytest.skip("MiniLM model not present")
    from PIL import Image, ImageDraw
    d = tmp_path_factory.mktemp("corpus")
    data = tmp_path_factory.mktemp("data")

    def text_img(name, word):
        im = Image.new("RGB", (800, 300), "white")
        dr = ImageDraw.Draw(im)
        dr.text((40, 90), word, font=_font(90), fill="black")
        im.save(str(d / name))

    text_img("word_zebra.png", "ZEBRA")
    text_img("word_garden.png", "GARDEN")
    im = Image.new("RGB", (800, 300), "white")
    dr = ImageDraw.Draw(im)
    dr.rectangle([100, 80, 300, 220], fill="red", outline="black")
    dr.ellipse([400, 80, 600, 220], fill="blue")
    im.save(str(d / "shapes_no_text.png"))
    (d / "notes_quokka.txt").write_text(
        "Field notes about a quokka encountered on the trail.\n")
    filler = ("lorem ipsum dolor sit amet consectetur adipiscing elit "
              "sed do eiusmod tempor incididunt ut labore et dolore ")
    (d / "long_doc.txt").write_text(
        (filler * 6) + "and then the quokka appeared. " + (filler * 2))
    dropit_ai.build_index(str(d), str(data))
    return str(d), str(data)


def _names(result):
    return [r["name"] for r in result["results"]]


def test_garbage_keyword_zero_results(corpus):
    d, data = corpus
    assert _names(dropit_ai.search_files(d, data, "safkjaeoifjeoije")) == []


def test_picture_text_word_exact_only(corpus):
    d, data = corpus
    assert _names(dropit_ai.search_files(d, data, "zebra")) == ["word_zebra.png"]
    assert _names(dropit_ai.search_files(d, data, "garden")) == ["word_garden.png"]


def test_buried_keyword_in_long_document_found(corpus):
    d, data = corpus
    names = _names(dropit_ai.search_files(d, data, "quokka"))
    assert "long_doc.txt" in names
    assert "notes_quokka.txt" in names
    assert "shapes_no_text.png" not in names


def test_unrelated_single_words_no_results(corpus):
    d, data = corpus
    # No beach/car photo exists in this corpus; text-image noise must
    # not invent one (MiniLM gives a GARDEN text image 0.35 for "beach").
    assert _names(dropit_ai.search_files(d, data, "beach")) == []
    assert _names(dropit_ai.search_files(d, data, "car")) == []


def test_ocr_reads_clear_text_and_blank_shapes(corpus):
    d, _ = corpus
    assert "ZEBRA" in dropit_ai._ocr_text(os.path.join(d, "word_zebra.png"))
    assert dropit_ai._ocr_text(os.path.join(d, "shapes_no_text.png")) == ""
