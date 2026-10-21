from __future__ import annotations

import threading
from typing import Protocol
import urllib.error

_translation_lock = threading.Lock()


class TranslationModel(Protocol):
    def translate(self, text: str) -> str: ...


_translation_model: TranslationModel | None = None


def _get_translation_model() -> TranslationModel:
    global _translation_model
    with _translation_lock:
        if _translation_model is not None:
            return _translation_model

        try:
            import argostranslate.package
            import argostranslate.translate
            from requests.exceptions import RequestException
        except ImportError as error:
            raise RuntimeError(
                "Local English translations need Argos Translate. Install the "
                "project requirements, then try again."
            ) from error

        installed_languages = argostranslate.translate.get_installed_languages()
        chinese = next(
            (language for language in installed_languages if language.code == "zh"),
            None,
        )
        english = next(
            (language for language in installed_languages if language.code == "en"),
            None,
        )
        translation = chinese.get_translation(english) if chinese and english else None

        if translation is None:
            try:
                argostranslate.package.update_package_index()
                package = next(
                    (
                        item
                        for item in argostranslate.package.get_available_packages()
                        if item.from_code == "zh" and item.to_code == "en"
                    ),
                    None,
                )
                if package is None:
                    raise RuntimeError(
                        "No Chinese-to-English local translation model is available."
                    )
                argostranslate.package.install_from_path(package.download())
            except (urllib.error.URLError, RequestException, OSError) as error:
                raise RuntimeError(
                    "Could not download the Chinese-to-English model for local "
                    "translation. Check your internet connection and try again."
                ) from error

            installed_languages = argostranslate.translate.get_installed_languages()
            chinese = next(
                (language for language in installed_languages if language.code == "zh"),
                None,
            )
            english = next(
                (language for language in installed_languages if language.code == "en"),
                None,
            )
            translation = chinese.get_translation(english) if chinese and english else None

        if translation is None:
            raise RuntimeError(
                "The Chinese-to-English model installed, but Argos Translate "
                "could not load it. Restart the app and try again."
            )
        _translation_model = translation
        return translation


def generate_translations(lines: list[str]) -> list[str]:
    """Translate Chinese dialogue lines to English using a local model."""
    translation = _get_translation_model()
    return [translation.translate(line) for line in lines]
