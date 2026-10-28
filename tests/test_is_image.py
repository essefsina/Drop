"""Unit tests for dropit_ai.is_image — the gate that decides whether a
file gets the image path in AI search (OCR / CLIP vision embeddings).

Covers every supported extension, case-insensitivity (phone cameras
write .JPG as often as .jpg), and the rejections: documents, video,
and extensionless names must not take the image path.
"""
from dropit_ai import is_image


def test_all_supported_extensions():
    for ext in ["jpg", "jpeg", "png", "webp", "bmp", "gif"]:
        assert is_image(f"photo.{ext}"), ext


def test_extension_matching_is_case_insensitive():
    assert is_image("IMG_1234.JPG")
    assert is_image("screenshot.JPEG")
    assert is_image("pic.PNG")
    assert is_image("scan.WebP")


def test_non_image_files_rejected():
    for name in ["report.pdf", "notes.txt", "song.mp3", "clip.mp4",
                 "archive.zip", "page.html", "data.json"]:
        assert not is_image(name), name


def test_extensionless_and_dotfile_names_rejected():
    assert not is_image("README")
    assert not is_image("photo")
    assert not is_image("")


def test_extension_must_be_exact():
    # A longer suffix that merely contains an image extension is not
    # an image (e.g. a JPEG2000 file is not in the supported set).
    assert not is_image("photo.jpg2")
    assert not is_image("photo.png.txt")
    assert not is_image("photo.jpeg2000")
