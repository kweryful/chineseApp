from __future__ import annotations

import array
import difflib
import math
import os
import re
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

_model_lock = threading.Lock()
_model = None
_model_name = ""
_AUDIO_SAMPLE_RATE = 16_000
_SILENCE_FRAME_SECONDS = 0.01
_MIN_SILENCE_SECONDS = 0.04


def normalize_text(text: str) -> str:
    return "".join(
        character.lower()
        for character in text
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def strip_speaker_label(text: str) -> str:
    return re.sub(r"^\s*[^：:\r\n]{1,16}[：:]\s*", "", text, count=1)


def _decode_audio(audio_path: str | Path, sample_rate: int) -> array.array[int]:
    import imageio_ffmpeg

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        decoded = subprocess.run(command, check=True, capture_output=True).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Could not decode the audio to locate quiet clip boundaries: {detail}"
        ) from error

    samples = array.array("h")
    samples.frombytes(decoded)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _quiet_region(
    samples: Sequence[int],
    sample_rate: int,
    start: float,
    end: float,
) -> tuple[float, float] | None:
    frame_size = max(1, round(sample_rate * _SILENCE_FRAME_SECONDS))
    first_sample = max(0, round(start * sample_rate))
    last_sample = min(len(samples), round(end * sample_rate))
    if last_sample - first_sample < frame_size * math.ceil(
        _MIN_SILENCE_SECONDS / _SILENCE_FRAME_SECONDS
    ):
        return None

    frame_levels: list[float] = []
    frame_starts: list[int] = []
    for frame_start in range(first_sample, last_sample - frame_size + 1, frame_size):
        frame_end = frame_start + frame_size
        mean_square = sum(
            samples[index] * samples[index]
            for index in range(frame_start, frame_end)
        ) / frame_size
        frame_levels.append(math.sqrt(mean_square) / 32768)
        frame_starts.append(frame_start)

    if not frame_levels:
        return None

    threshold = min(0.035, max(0.008, max(frame_levels) * 0.18))
    quiet_frames = [level <= threshold for level in frame_levels]
    minimum_run = math.ceil(_MIN_SILENCE_SECONDS / _SILENCE_FRAME_SECONDS)
    best_run: tuple[int, int] | None = None
    run_start: int | None = None
    for index, is_quiet in enumerate((*quiet_frames, False)):
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            if index - run_start >= minimum_run and (
                best_run is None
                or index - run_start > best_run[1] - best_run[0]
            ):
                best_run = (run_start, index)
            run_start = None

    if best_run is None:
        return None
    quiet_start = frame_starts[best_run[0]]
    quiet_end = frame_starts[best_run[1] - 1] + frame_size
    return quiet_start / sample_rate, quiet_end / sample_rate


def _find_occurrences(text: str, needle: str, start: int) -> list[int]:
    positions: list[int] = []
    position = text.find(needle, start)
    while position != -1 and len(positions) < 300:
        positions.append(position)
        position = text.find(needle, position + 1)
    return positions


def _candidate_starts(reference: str, transcript: str, cursor: int) -> list[int]:
    starts: set[int] = set()
    for size in (4, 3, 2):
        anchors = range(0, len(reference) - size + 1, max(1, size // 2))
        matches: list[tuple[int, int, list[int]]] = []
        for reference_position in anchors:
            positions = _find_occurrences(
                transcript, reference[reference_position : reference_position + size], cursor
            )
            if positions:
                matches.append((len(positions), reference_position, positions))
        if matches:
            for _, reference_position, positions in sorted(matches)[:8]:
                for position in positions[:60]:
                    estimate = max(cursor, position - reference_position)
                    for offset in (-3, 0, 3):
                        starts.add(max(cursor, estimate + offset))
            break

    if not starts:
        stride = max(1, len(reference) // 4, len(transcript) // 2000)
        starts.update(range(cursor, max(cursor + 1, len(transcript) - len(reference) + 1), stride))
    return sorted(starts)


def align_lines_to_words(
    lines: list[str],
    words: Iterable[tuple[str, float, float]],
    duration: float,
    audio_samples: Sequence[int] | None = None,
    sample_rate: int = _AUDIO_SAMPLE_RATE,
) -> list[dict[str, float | int | str | None]]:
    transcript_parts: list[str] = []
    character_times: list[tuple[float, float]] = []
    for word, start, end in words:
        normalized = normalize_text(word)
        transcript_parts.append(normalized)
        if normalized:
            character_duration = max(0.0, end - start) / len(normalized)
            character_times.extend(
                (
                    start + offset * character_duration,
                    start + (offset + 1) * character_duration,
                )
                for offset in range(len(normalized))
            )
    transcript = "".join(transcript_parts)

    results: list[dict[str, float | int | str | None]] = []
    character_ranges: list[tuple[float, float] | None] = []
    cursor = 0
    previous_end = 0.0
    for index, line in enumerate(lines):
        reference = normalize_text(strip_speaker_label(line))
        best: tuple[float, int, int] | None = None
        if len(reference) >= 2 and cursor < len(transcript):
            for start in _candidate_starts(reference, transcript, cursor):
                if start >= len(transcript):
                    continue
                minimum = max(1, int(len(reference) * 0.65))
                maximum = min(
                    len(transcript) - start,
                    max(minimum, int(len(reference) * 1.4) + 1),
                )
                step = max(1, len(reference) // 12)
                window_lengths = set(range(minimum, maximum + 1, step))
                window_lengths.update((minimum, maximum))
                window_lengths.update(
                    length
                    for length in range(len(reference) - 2, len(reference) + 3)
                    if minimum <= length <= maximum
                )
                for window_length in window_lengths:
                    end = start + window_length
                    candidate = transcript[start:end]
                    score = difflib.SequenceMatcher(
                        None, reference, candidate, autojunk=False
                    ).ratio()
                    if best is None or score > best[0] or (
                        score == best[0]
                        and (
                            start < best[1]
                            or (
                                start == best[1]
                                and abs(window_length - len(reference))
                                < abs((best[2] - best[1]) - len(reference))
                            )
                        )
                    ):
                        best = (score, start, end)

        threshold = 0.78 if len(reference) < 8 else 0.62
        if best is None or best[0] < threshold:
            results.append(
                {
                    "line": index,
                    "start": None,
                    "end": None,
                    "confidence": 0.0,
                    "matched_text": "",
                    "pause_after": None,
                }
            )
            character_ranges.append(None)
            continue

        score, start_index, end_index = best
        previous_character_end = (
            character_times[start_index - 1][1] if start_index > 0 else 0.0
        )
        start_padding = 0.55 if start_index > 0 and audio_samples is None else 0.04
        start_time = max(
            previous_end,
            previous_character_end,
            0.0,
            character_times[start_index][0] - start_padding,
        )
        end_time = min(duration, character_times[end_index - 1][1] + 0.13)
        if end_time <= start_time:
            results.append(
                {
                    "line": index,
                    "start": None,
                    "end": None,
                    "confidence": 0.0,
                    "matched_text": "",
                    "pause_after": None,
                }
            )
            character_ranges.append(None)
            continue

        results.append(
            {
                "line": index,
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "confidence": round(score, 3),
                "matched_text": transcript[start_index:end_index],
                "pause_after": None,
            }
        )
        character_ranges.append(
            (character_times[start_index][0], character_times[end_index - 1][1])
        )
        cursor = end_index
        previous_end = end_time

    for index in range(len(results) - 1):
        current_range = character_ranges[index]
        next_range = character_ranges[index + 1]
        if current_range is not None and next_range is not None:
            results[index]["pause_after"] = round(max(0.0, next_range[0] - current_range[1]), 3)
            if audio_samples is not None:
                quiet_region = _quiet_region(
                    audio_samples, sample_rate, current_range[1], next_range[0]
                )
                if quiet_region is not None:
                    quiet_start, quiet_end = quiet_region
                    results[index]["end"] = round(quiet_start, 3)
                    results[index + 1]["start"] = round(quiet_end, 3)

    return results


def _get_model():
    global _model, _model_name
    model_name = os.environ.get("DIALOGUE_WHISPER_MODEL", "base")
    with _model_lock:
        if _model is None or _model_name != model_name:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "Automatic sync needs faster-whisper. Install the project "
                    "requirements, then try again."
                ) from error
            _model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _model_name = model_name
    return _model


def transcribe_and_align(
    audio_path: str | Path, lines: list[str], duration: float
) -> dict[str, object]:
    model = _get_model()
    segments, _ = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )
    words: list[tuple[str, float, float]] = []
    for segment in segments:
        for word in segment.words or []:
            if word.word.strip():
                words.append((word.word, float(word.start), float(word.end)))
    if not words:
        raise RuntimeError(
            "No speech was recognized. Check the audio and try again, or set the line times manually."
        )

    audio_samples = _decode_audio(audio_path, _AUDIO_SAMPLE_RATE)
    matches = align_lines_to_words(
        lines, words, duration, audio_samples, _AUDIO_SAMPLE_RATE
    )
    recognized_text = "".join(word for word, _, _ in words)
    return {"matches": matches, "recognized_text": recognized_text}
