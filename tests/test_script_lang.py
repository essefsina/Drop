"""Unit tests for dropit_mt._script_lang — the Unicode-range step of
offline language detection.

Non-Latin scripts are identified by character ranges before any
word-frequency fallback runs, so a dominant script is definitive:
Japanese kana, Korean hangul, Chinese characters, Arabic, Devanagari,
Bengali and Cyrillic each map to one language code. Latin text and
text where no script clears its share threshold return None, which
callers treat as "unknown" rather than guessing English.
"""
from dropit_mt import _script_lang

SAMPLES = {
    "ja": "こんにちは世界ありがとうございますこれは家と水についてのレポートです",
    "ko": "안녕하세요세계감사합니다이것은집과물에대한보고서입니다",
    "zh": "你好世界谢谢这是一个关于房子和水的报告今天",
    "ar": "مرحبا بالعالم شكرا لك هذا تقرير عن البيت والماء اليوم",
    "hi": "नमस्ते दुनिया धन्यवाद यह घर और पानी के बारे में एक रिपोर्ट है",
    "bn": "হ্যালো বিশ্ব ধন্যবাদ এটি বাড়ি এবং জল সম্পর্কে একটি প্রতিবেদন",
    "ru": "Привет мир спасибо пожалуйста здравствуйте человек дом вода хлеб",
}


def test_each_script_maps_to_its_language():
    for lang, sample in SAMPLES.items():
        assert _script_lang(sample) == lang, lang


def test_kana_wins_over_kanji_in_japanese():
    # Kana is checked before the CJK range, so Japanese text carrying
    # kanji still resolves to ja, not zh.
    assert _script_lang("こんにちは世界です") == "ja"


def test_latin_text_returns_none():
    assert _script_lang(
        "Hello world this is a plain English report about the house"
    ) is None


def test_below_threshold_mixed_text_returns_none():
    # Six Cyrillic letters in a long English sentence stay under the
    # 10% Cyrillic threshold, so the result is unknown, not Russian.
    text = (
        "Hello world this is a long English report about the house "
        "and the water today with one word Привет in it somewhere"
    )
    assert _script_lang(text) is None


def test_empty_text_returns_none():
    assert _script_lang("") is None
