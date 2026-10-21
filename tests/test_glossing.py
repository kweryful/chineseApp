import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import glossing
import study_fields


class TranslationTests(unittest.TestCase):
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
