"""Unit tests for dropit_mt.detect_lang — offline language detection.

Covers the Latin common-word languages plus script-based detection
(ru/ja/zh/ar) and the None/ambiguous edge cases.
"""
from dropit_mt import detect_lang

# Each sample is long enough to carry a clear signal; verified against
# the real implementation so the tests pin current behavior.
SAMPLES = {
    "en": "Hello world, thanks for reading this good morning report "
          "about the house and the water",
    "fr": "Bonjour tout le monde merci beaucoup pour ce rapport "
          "sur la maison et le fromage",
    "es": "Hola mundo gracias por leer este informe sobre la casa "
          "y el agua mañana",
    "de": "Guten Morgen Welt danke für das Lesen dieses Berichts "
          "über das Haus und das Wasser",
    "it": "Buongiorno mondo grazie per aver letto questo rapporto "
          "sulla casa e il vino",
    "pt": "Olá mundo obrigado por ler este relatório sobre a casa "
          "e o vinho amanhã",
    "nl": "Goedemorgen wereld bedankt voor het lezen van dit rapport "
          "over het huis en het water",
    "ru": "Привет мир спасибо пожалуйста здравствуйте человек дом "
           "вода хлеб",
    "ja": "こんにちは世界ありがとうございますこれは家と水についてのレポートです",
    "zh": "你好世界谢谢这是一个关于房子和水的报告今天",
    "ar": "مرحبا بالعالم شكرا لك هذا تقرير عن البيت والماء اليوم",
}


def test_each_supported_language():
    for lang, text in SAMPLES.items():
        assert detect_lang(text) == lang, f"expected {lang}"


def test_short_text_still_detects():
    assert detect_lang("hello world") == "en"
    assert detect_lang("bonjour merci") == "fr"


def test_empty_and_blank_return_none():
    assert detect_lang("") is None
    assert detect_lang("   ") is None
    assert detect_lang(None) is None


def test_non_text_returns_none():
    assert detect_lang("x7! @#$") is None
    assert detect_lang("12345 67890") is None


def test_gibberish_words_return_none():
    assert detect_lang("xyzzy plugh qwerty asdf zxcv") is None
