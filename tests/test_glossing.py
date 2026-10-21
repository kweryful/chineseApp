import re
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import glossing
import study_fields
from third_party.anki_chinese_support_3.chinese.hanzi import split_hanzi


class TranslationTests(unittest.TestCase):
    def test_full_cut_is_used_for_gloss_terms_but_not_reading_segments(self) -> None:
        reading_segments = split_hanzi("来得及")
        gloss_segments = split_hanzi("其实我考得也不怎么样。", cut_all=True)

        self.assertEqual(reading_segments, ["来得及"])
        self.assertIn("考", gloss_segments)
        self.assertIn("考得", split_hanzi("其实我考得也不怎么样。"))

    def test_translates_each_line_in_input_order(self) -> None:
        class Translation:
            def translate(self, text: str) -> str:
                return f"English: {text}"

        with patch.object(glossing, "_get_translation_model", return_value=Translation()):
            self.assertEqual(
                glossing.generate_translations(["你好。", "再见。"]),
                ["English: 你好。", "English: 再见。"],
            )

    def test_tone_sandhi_matches_addon_sample_for_yi(self) -> None:
        def tone_number(syllable: str) -> str:
            return {"yī": "1", "bān": "1"}[syllable]

        def no_tone(syllable: str) -> str:
            return {"yī": "yi"}[syllable]

        transcribe = SimpleNamespace(
            tone_number=tone_number,
            no_tone=no_tone,
            accentuate=lambda _parts, _target: ["yì"],
        )
        self.assertEqual(
            study_fields._apply_tone_sandhi(
                ["一", "般"],
                ["yī", "bān"],
                transcribe,
            ),
            ["yì", "bān"],
        )

    def test_manual_numbered_pinyin_overrides_vocabulary_ruby(self) -> None:
        hanzi = SimpleNamespace(
            split_hanzi=lambda text, grouped=True: [text] if grouped else list(text)
        )
        transcribe = SimpleNamespace(
            transcribe=lambda _words, _target, _type: ["xuè"],
            split_transcript=lambda text, _target, grouped=False: (
                ["xuè"]
                if text == "xuè"
                else re.findall(r"[a-züv]+[1-5]", text, flags=re.IGNORECASE)
            ),
            tone_number=lambda _syllable: "4",
            no_tone=lambda _syllable: "xue",
            accentuate=lambda syllables, _target: [
                {"xue4": "xuè", "xie3": "xiě"}[syllable]
                for syllable in syllables
            ],
        )
        color = SimpleNamespace(
            colorize=lambda _parts, _target: "",
            colorize_fuse=lambda _chars, syllables, ruby=False: (
                f"<ruby>血<rt>{syllables[0]}</rt></ruby>" if ruby else ""
            ),
        )
        translate = SimpleNamespace(translate=lambda _text, _target: "blood")
        util = SimpleNamespace(cleanup=lambda text: text)

        with patch.object(
            study_fields,
            "_get_engine",
            return_value=(hanzi, transcribe, color, translate, util),
        ):
            generated = study_fields.generate_study_fields(["血"], ["xie3"])

        self.assertEqual(generated[0]["ruby"], "<ruby>血<rt>xiě</rt></ruby>")

    def test_manual_numbered_pinyin_requires_one_syllable_per_character(self) -> None:
        hanzi = SimpleNamespace(
            split_hanzi=lambda text, grouped=True: [text] if grouped else list(text)
        )
        transcribe = SimpleNamespace(
            transcribe=lambda _words, _target, _type: ["xuè"],
            split_transcript=lambda text, _target, grouped=False: (
                ["xuè"]
                if text == "xuè"
                else re.findall(r"[a-züv]+[1-5]", text, flags=re.IGNORECASE)
            ),
            tone_number=lambda _syllable: "4",
            no_tone=lambda _syllable: "xue",
            accentuate=lambda syllables, _target: syllables,
        )
        color = SimpleNamespace(
            colorize=lambda _parts, _target: "",
            colorize_fuse=lambda _chars, _syllables, ruby=False: "",
        )
        translate = SimpleNamespace(translate=lambda _text, _target: "blood")
        util = SimpleNamespace(cleanup=lambda text: text)

        with patch.object(
            study_fields,
            "_get_engine",
            return_value=(hanzi, transcribe, color, translate, util),
        ), self.assertRaisesRegex(ValueError, "has 2 syllables but the word has 1 characters"):
            study_fields.generate_study_fields(["血"], ["xue4xie3"])

    def test_downloads_chinese_english_model_once_when_not_installed(self) -> None:
        installed = False

        class Translation:
            def translate(self, text: str) -> str:
                return f"English: {text}"

        translation = Translation()

        class Language:
            def __init__(self, code: str) -> None:
                self.code = code

            def get_translation(self, target: "Language") -> Translation | None:
                if self.code == "zh" and target.code == "en" and installed:
                    return translation
                return None

        class AvailablePackage:
            from_code = "zh"
            to_code = "en"

            def download(self) -> str:
                return "zh-en.argosmodel"

        root = ModuleType("argostranslate")
        root.__path__ = []
        package_module = ModuleType("argostranslate.package")
        package_module.update_package_index = lambda: None
        package = AvailablePackage()
        package_module.get_available_packages = lambda: [package]

        def install_from_path(path: str) -> None:
            nonlocal installed
            self.assertEqual(path, "zh-en.argosmodel")
            installed = True

        package_module.install_from_path = install_from_path

        translate_module = ModuleType("argostranslate.translate")
        translate_module.get_installed_languages = lambda: [
            Language("zh"),
            Language("en"),
        ]
        root.package = package_module
        root.translate = translate_module

        with (
            patch.dict(
                sys.modules,
                {
                    "argostranslate": root,
                    "argostranslate.package": package_module,
                    "argostranslate.translate": translate_module,
                },
            ),
            patch.object(glossing, "_translation_model", None),
        ):
            first_model = glossing._get_translation_model()
            second_model = glossing._get_translation_model()

        self.assertIs(first_model, translation)
        self.assertIs(second_model, translation)


if __name__ == "__main__":
    unittest.main()
