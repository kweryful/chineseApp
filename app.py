from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import imageio_ffmpeg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from alignment import transcribe_and_align
from glossing import generate_translations
from study_fields import generate_study_fields

BASE_DIR = Path(__file__).resolve().parent
MAX_AUDIO_BYTES = 100 * 1024 * 1024
MAX_LINES = 500

app = FastAPI(title="Dialogue Workshop")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class TranslationRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=MAX_LINES)


class StudyFieldsRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=MAX_LINES)
    vocabulary: list[str] = Field(default_factory=list, max_length=MAX_LINES)
    pronunciations: list[str] = Field(default_factory=list, max_length=MAX_LINES)


class VocabularyFieldsRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=MAX_LINES)
    pronunciations: list[str] = Field(default_factory=list, max_length=MAX_LINES)


class AlignmentRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=MAX_LINES)
    duration: float = Field(gt=0)


class DialogueLine(BaseModel):
    sentence: str = Field(min_length=1, max_length=5000)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    gloss: str = Field(default="", max_length=5000)
    reading: str = Field(default="", max_length=250_000)
    ruby: str = Field(default="", max_length=250_000)
    dictionary_gloss: str = Field(default="", max_length=500_000)
    Word: str = Field(default="", max_length=25_000)
    WordDef: str = Field(default="", max_length=500_000)
    WordRuby: str = Field(default="", max_length=250_000)


class VocabularyExportEntry(BaseModel):
    hanzi: str = Field(min_length=1, max_length=500)
    pinyin: str = Field(default="", max_length=200)
    definition: str = Field(min_length=1, max_length=5000)


class ExportManifest(BaseModel):
    title: str = Field(default="dialogue", max_length=120)
    source_folder: str = Field(default="", max_length=500)
    duration: float = Field(gt=0)
    lines: list[DialogueLine] = Field(min_length=1, max_length=MAX_LINES)
    vocabulary: list[VocabularyExportEntry] = Field(default_factory=list, max_length=MAX_LINES)


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", title.strip(), flags=re.UNICODE).strip(".-")
    return cleaned[:80] or "dialogue"


def _ffmpeg_path() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (RuntimeError, OSError) as error:
        raise HTTPException(
            status_code=503,
            detail="FFmpeg is not available. Reinstall the app dependencies and try again.",
        ) from error


@app.get("/")
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/translations")
def translate(request: TranslationRequest) -> dict[str, list[str]]:
    try:
        translations = generate_translations(request.lines)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if len(translations) != len(request.lines) or any(
        not isinstance(item, str) for item in translations
    ):
        raise HTTPException(
            status_code=500,
            detail="The local translator must return one English translation per line.",
        )
    return {"translations": translations}


@app.post("/api/study-fields")
def generate_line_study_fields(
    request: StudyFieldsRequest,
) -> dict[str, list[dict[str, str]]]:
    if request.pronunciations and len(request.pronunciations) != len(request.vocabulary):
        raise HTTPException(
            status_code=422,
            detail="Provide one pronunciation override per vocabulary word.",
        )
    try:
        fields = generate_study_fields(request.lines)
        vocabulary_fields = (
            generate_study_fields(
                request.vocabulary,
                request.pronunciations or [""] * len(request.vocabulary),
            )
            if request.vocabulary
            else []
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if len(fields) != len(request.lines) or any(
        not isinstance(item, dict)
        or not all(
            isinstance(item.get(field), str)
            for field in ("reading", "ruby", "dictionary_gloss")
        )
        for item in fields
    ) or len(vocabulary_fields) != len(request.vocabulary) or any(
        not isinstance(item, dict) or not isinstance(item.get("ruby"), str)
        for item in vocabulary_fields
    ):
        raise HTTPException(
            status_code=500,
            detail="The Chinese Support engine must return reading, ruby, and gloss for every line and ruby for every vocabulary item.",
        )
    return {
        "lines": fields,
        "vocabulary": [{"ruby": item["ruby"]} for item in vocabulary_fields],
    }


@app.post("/api/vocabulary-fields")
def generate_vocabulary_fields(
    request: VocabularyFieldsRequest,
) -> dict[str, list[dict[str, str]]]:
    if request.pronunciations and len(request.pronunciations) != len(request.words):
        raise HTTPException(
            status_code=422,
            detail="Provide one pronunciation override per vocabulary word.",
        )
    try:
        fields = generate_study_fields(
            request.words,
            request.pronunciations or [""] * len(request.words),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if len(fields) != len(request.words) or any(
        not isinstance(item, dict) or not isinstance(item.get("ruby"), str)
        for item in fields
    ):
        raise HTTPException(
            status_code=500,
            detail="The Chinese Support engine must return ruby for every vocabulary item.",
        )
    return {"words": [{"ruby": item["ruby"]} for item in fields]}


@app.post("/api/align")
async def align_audio(
    audio: Annotated[UploadFile, File()],
    request_json: Annotated[str, Form()],
) -> dict[str, object]:
    if Path(audio.filename or "").suffix.lower() != ".mp3":
        raise HTTPException(status_code=415, detail="Please choose an MP3 audio file.")

    try:
        request = AlignmentRequest.model_validate_json(request_json)
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid dialogue alignment data.") from error

    audio_data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(audio_data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The MP3 must be 100 MB or smaller.")
    if not audio_data:
        raise HTTPException(status_code=422, detail="The selected MP3 file is empty.")

    with tempfile.TemporaryDirectory(prefix="dialogue-align-") as temp_dir:
        audio_path = Path(temp_dir) / "source.mp3"
        audio_path.write_bytes(audio_data)
        try:
            return await run_in_threadpool(
                transcribe_and_align,
                audio_path,
                request.lines,
                request.duration,
            )
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/export")
async def export_dialogue(
    audio: Annotated[UploadFile, File()],
    manifest: Annotated[str, Form()],
) -> StreamingResponse:
    if Path(audio.filename or "").suffix.lower() != ".mp3":
        raise HTTPException(status_code=415, detail="Please choose an MP3 audio file.")

    try:
        data = ExportManifest.model_validate_json(manifest)
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid dialogue timing data.") from error

    for index, line in enumerate(data.lines, start=1):
        if line.end <= line.start:
            raise HTTPException(
                status_code=422,
                detail=f"Line {index} must end after it starts.",
            )
        if line.end > data.duration + 0.05:
            raise HTTPException(
                status_code=422,
                detail=f"Line {index} ends after the audio duration.",
            )

    audio_data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(audio_data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The MP3 must be 100 MB or smaller.")
    if not audio_data:
        raise HTTPException(status_code=422, detail="The selected MP3 file is empty.")

    ffmpeg = _ffmpeg_path()
    audio_stem = _safe_title(Path(audio.filename or "dialogue.mp3").stem)
    source_folder = data.source_folder.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    clip_prefix = (
        f"{_safe_title(source_folder)}-{audio_stem}"
        if source_folder
        else audio_stem
    )
    archive_buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="dialogue-workshop-") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "source.mp3"
        input_path.write_bytes(audio_data)
        exported_lines: list[dict[str, object]] = []

        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, line in enumerate(data.lines, start=1):
                clip_name = f"{clip_prefix}-line-{index:03}.mp3"
                clip_path = temp_path / clip_name
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{line.start:.3f}",
                    "-i",
                    str(input_path),
                    "-t",
                    f"{line.end - line.start:.3f}",
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(clip_path),
                ]
                try:
                    subprocess.run(command, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as error:
                    message = error.stderr.strip() or "FFmpeg could not process the MP3."
                    raise HTTPException(
                        status_code=422,
                        detail=f"Could not create clip for line {index}: {message}",
                    ) from error
                if not clip_path.is_file() or clip_path.stat().st_size == 0:
                    raise HTTPException(
                        status_code=422,
                        detail=f"No audio was produced for line {index}; check its timing.",
                    )

                archive.write(clip_path, arcname=clip_name)
                exported_lines.append(
                    {
                        "number": index,
                        "sentence": line.sentence,
                        "gloss": line.gloss,
                        "reading": line.reading,
                        "ruby": line.ruby,
                        "dictionary_gloss": line.dictionary_gloss,
                        "Word": line.Word,
                        "WordDef": line.WordDef,
                        "WordRuby": line.WordRuby,
                        "clip": clip_name,
                    }
                )

            dialogue = {
                "title": data.title,
                "duration": data.duration,
                "lines": [
                    {
                        key: value
                        for key, value in line.items()
                    }
                    for line in exported_lines
                ],
            }
            archive.writestr(
                "dialogue.json",
                json.dumps(dialogue, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                f"{audio_stem}.txt",
                "\n".join(line.sentence for line in data.lines),
            )
            if data.vocabulary:
                vocabulary_text = "\n".join(
                    f"{entry.hanzi}\t{entry.pinyin}\t{entry.definition}"
                    for entry in data.vocabulary
                )
                archive.writestr(f"{audio_stem}-vocab.txt", vocabulary_text)

            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(
                csv_buffer,
                fieldnames=[
                    "number",
                    "sentence",
                    "gloss",
                    "reading",
                    "ruby",
                    "dictionary_gloss",
                    "Word",
                    "WordDef",
                    "WordRuby",
                    "clip",
                ],
            )
            writer.writeheader()
            writer.writerows(exported_lines)
            archive.writestr("dialogue.csv", "\ufeff" + csv_buffer.getvalue())

    archive_buffer.seek(0)
    filename = f"{_safe_title(data.title)}-dialogue.zip"
    encoded_filename = quote(filename, safe="")
    return StreamingResponse(
        archive_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dialogue.zip"; filename*=UTF-8\'\'{encoded_filename}'
            )
        },
    )
