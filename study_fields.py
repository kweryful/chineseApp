from __future__ import annotations

import hashlib
import importlib
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

_UPSTREAM_COMMIT = "306f3a32f453d33d949532c1325c1a689bbab7c2"
_DATABASE_GIT_SHA = "3c98ddb26eefbd10e72cb8f9a185cb44a0ac58f2"
_DATABASE_SIZE = 76_095_488
_DATABASE_URL = (
    "https://raw.githubusercontent.com/kweryful/anki-chinese-support-3/"
    f"{_UPSTREAM_COMMIT}/chinese/data/db/chinese.db"
)
_engine_lock = threading.RLock()
_engine_modules: (
    tuple[ModuleType, ModuleType, ModuleType, ModuleType, ModuleType] | None
) = None


def _database_path() -> Path:
    data_dir = os.environ.get("DIALOGUE_WORKSHOP_DATA_DIR")
    if data_dir:
        root = Path(data_dir)
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "DialogueWorkshop"
    else:
        root = Path.home() / ".cache" / "dialogue-workshop"
    return root / "anki-chinese-support-3" / "chinese.db"


def _matches_upstream_database(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size != _DATABASE_SIZE:
        return False

    digest = hashlib.sha1(f"blob {_DATABASE_SIZE}\0".encode("ascii"))
    with path.open("rb") as database:
        for chunk in iter(lambda: database.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == _DATABASE_GIT_SHA


def _ensure_database() -> Path:
    target = _database_path()
    if _matches_upstream_database(target):
        return target

    temporary_path = target.with_suffix(".db.download")
    digest = hashlib.sha1(f"blob {_DATABASE_SIZE}\0".encode("ascii"))
    downloaded = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(_DATABASE_URL, timeout=60) as response:
            with temporary_path.open("wb") as database:
                while chunk := response.read(1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > _DATABASE_SIZE:
                        raise RuntimeError(
                            "The Chinese dictionary download was larger than expected."
                        )
                    database.write(chunk)
                    digest.update(chunk)

        if downloaded != _DATABASE_SIZE or digest.hexdigest() != _DATABASE_GIT_SHA:
            raise RuntimeError(
                "The downloaded Chinese dictionary did not match the verified "
                "upstream version. Please retry later."
            )
        temporary_path.replace(target)
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(
            "Could not download the local Chinese dictionary required for readings "
            "and glosses. Check your internet connection and try again."
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)
    return target


def _get_engine() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType, ModuleType]:
    global _engine_modules
    with _engine_lock:
        if _engine_modules is not None:
            return _engine_modules

        database_path = _ensure_database()
        os.environ["DIALOGUE_WORKSHOP_CHINESE_DB"] = str(database_path)
        try:
            package = "third_party.anki_chinese_support_3.chinese"
            importlib.import_module(f"{package}.main")
            hanzi = importlib.import_module(f"{package}.hanzi")
            transcribe = importlib.import_module(f"{package}.transcribe")
            color = importlib.import_module(f"{package}.color")
            translate = importlib.import_module(f"{package}.translate")
        except ModuleNotFoundError as error:
            if error.name == "jieba":
                detail = (
                    "Local Chinese readings and dictionary glosses need Jieba. "
                    "Install the project requirements and try again."
                )
            else:
                detail = "Could not load the bundled Chinese Support engine."
            raise RuntimeError(detail) from error
        except ImportError as error:
            raise RuntimeError(
                "Could not load the bundled Chinese Support engine."
            ) from error

        util = importlib.import_module(f"{package}.util")
        _engine_modules = (hanzi, transcribe, color, translate, util)
        return _engine_modules


def _apply_tone_sandhi(
    characters: list[str],
    syllables: list[str],
    transcribe: ModuleType,
) -> list[str]:
    if len(characters) != len(syllables):
        return syllables

    adjusted = syllables.copy()
    for index, character in enumerate(characters[:-1]):
        following_character = characters[index + 1]
        if (
            character not in ("一", "不")
            or not any("\u3400" <= char <= "\u9fff" for char in following_character)
        ):
            continue
        following_tone = transcribe.tone_number(syllables[index + 1])
        current_tone = transcribe.tone_number(syllables[index])
        changed_tone = None
        if character == "一" and current_tone == "1":
            changed_tone = "2" if following_tone == "4" else "4"
        elif character == "不" and current_tone == "4" and following_tone == "4":
            changed_tone = "2"
        if changed_tone:
            base = transcribe.no_tone(syllables[index])
            adjusted[index] = transcribe.accentuate(
                [f"{base}{changed_tone}"], "pinyin"
            )[0]
    return adjusted


def generate_study_fields(lines: list[str]) -> list[dict[str, str]]:
    """Generate add-on-compatible pinyin, ruby, and dictionary gloss HTML."""
    with _engine_lock:
        hanzi, transcribe, color, translate, util = _get_engine()
        generated: list[dict[str, str]] = []
        for sentence in lines:
            cleaned = util.cleanup(sentence)
            source_words = hanzi.split_hanzi(cleaned)
            reading_parts = transcribe.transcribe(source_words, "pinyin", "simp")
            characters = hanzi.split_hanzi(cleaned, grouped=False)
            syllable_parts = [
                transcribe.split_transcript(part, "pinyin", grouped=False)
                for part in reading_parts
            ]
            syllables = [syllable for part in syllable_parts for syllable in part]
            syllables = _apply_tone_sandhi(characters, syllables, transcribe)
            cursor = 0
            adjusted_parts = []
            for part in syllable_parts:
                adjusted_parts.append(" ".join(syllables[cursor : cursor + len(part)]))
                cursor += len(part)
            reading = color.colorize(adjusted_parts, "pinyin")
            ruby_syllables = syllables
            ruby = color.colorize_fuse(characters, ruby_syllables, ruby=True)
            gloss = translate.translate(cleaned, "en")
            generated.append({"reading": reading, "ruby": ruby, "dictionary_gloss": gloss})
        return generated
