import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
from fastapi.testclient import TestClient

from app import _anki_sentence_with_bold_words, app


class DialogueAppTests(unittest.TestCase):
    def test_anki_q1_bolds_matching_vocabulary_words(self) -> None:
        self.assertEqual(
            _anki_sentence_with_bold_words("别吃惊。", "吃惊"),
            "别<b>吃惊</b>。",
        )
        self.assertEqual(
            _anki_sentence_with_bold_words("京剧很好。", "京剧,好"),
            "<b>京剧</b>很<b>好</b>。",
        )
        self.assertEqual(_anki_sentence_with_bold_words("别吃惊。", ""), "别吃惊。")

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cls.audio = subprocess.run(
            [
                cls.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                "-f",
                "mp3",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout

    def test_homepage_loads(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dialogue Workshop", response.text)
        self.assertNotIn('id="dialogue-title"', response.text)
        self.assertIn('id="vocabulary-input"', response.text)
        self.assertIn('id="vocabulary-toggle"', response.text)

    def test_translation_endpoint_returns_one_translation_per_line(self) -> None:
        with patch("app.generate_translations", return_value=["Hello.", "Goodbye."]):
            response = self.client.post(
                "/api/translations",
                json={"lines": ["你好。", "再见。"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"translations": ["Hello.", "Goodbye."]})

    def test_translation_endpoint_reports_local_model_setup_errors(self) -> None:
        with patch(
            "app.generate_translations",
            side_effect=RuntimeError("Could not download the local model."),
        ):
            response = self.client.post("/api/translations", json={"lines": ["你好。"]})
        self.assertEqual(response.status_code, 503)
        self.assertIn("local model", response.json()["detail"])

    def test_translation_endpoint_rejects_incomplete_translations(self) -> None:
        with patch("app.generate_translations", return_value=[]):
            response = self.client.post("/api/translations", json={"lines": ["你好。"]})
        self.assertEqual(response.status_code, 500)
        self.assertIn("one English translation per line", response.json()["detail"])

    def test_study_fields_endpoint_returns_addon_html_fields(self) -> None:
        generated = [
            {
                "reading": '<span class="tone4">yì</span>',
                "ruby": "<ruby>一<rt>yì</rt></ruby>",
                "dictionary_gloss": "❖ general",
            }
        ]
        with patch("app.generate_study_fields", return_value=generated):
            response = self.client.post(
                "/api/study-fields",
                json={"lines": ["一般情况下。"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"lines": generated, "vocabulary": []})

    def test_study_fields_endpoint_returns_vocabulary_ruby(self) -> None:
        line_fields = [
            {
                "reading": '<span class="tone4">lái</span>',
                "ruby": "<ruby>来<rt>lái</rt></ruby>",
                "dictionary_gloss": "❖ come",
            }
        ]
        vocabulary_fields = [
            {
                "reading": '<span class="tone4">lái</span>',
                "ruby": '<span class="tone4"><ruby>来<rt>lái</rt></ruby></span>',
                "dictionary_gloss": "❖ come",
            }
        ]
        with patch(
            "app.generate_study_fields",
            side_effect=[line_fields, vocabulary_fields],
        ):
            response = self.client.post(
                "/api/study-fields",
                json={"lines": ["来得及。"], "vocabulary": ["来得及"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lines"], line_fields)
        self.assertEqual(response.json()["vocabulary"], [{"ruby": vocabulary_fields[0]["ruby"]}])

    def test_vocabulary_fields_endpoint_returns_ruby(self) -> None:
        generated = [
            {
                "reading": '<span class="tone4">xuè</span>',
                "ruby": '<span class="tone3"><ruby>血<rt>xiě</rt></ruby></span>',
                "dictionary_gloss": "❖ blood",
            }
        ]
        with patch("app.generate_study_fields", return_value=generated) as generate:
            response = self.client.post(
                "/api/vocabulary-fields",
                json={"words": ["血"], "pronunciations": ["xie3"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        generate.assert_called_once_with(["血"], ["xie3"])
        self.assertEqual(
            response.json(),
            {"words": [{"ruby": '<span class="tone3"><ruby>血<rt>xiě</rt></ruby></span>'}]},
        )

    def test_vocabulary_fields_endpoint_rejects_incomplete_ruby(self) -> None:
        with patch("app.generate_study_fields", return_value=[{"reading": "lái"}]):
            response = self.client.post("/api/vocabulary-fields", json={"words": ["来得及"]})
        self.assertEqual(response.status_code, 500)
        self.assertIn("ruby for every vocabulary item", response.json()["detail"])

    def test_vocabulary_fields_endpoint_reports_invalid_pronunciation(self) -> None:
        with patch(
            "app.generate_study_fields",
            side_effect=ValueError("Pronunciation override has the wrong syllable count."),
        ):
            response = self.client.post(
                "/api/vocabulary-fields",
                json={"words": ["血"], "pronunciations": ["xue4xie3"]},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("syllable count", response.json()["detail"])

    def test_study_fields_endpoint_reports_dictionary_download_errors(self) -> None:
        with patch(
            "app.generate_study_fields",
            side_effect=RuntimeError("Could not download the local dictionary."),
        ):
            response = self.client.post("/api/study-fields", json={"lines": ["你好。"]})
        self.assertEqual(response.status_code, 503)
        self.assertIn("local dictionary", response.json()["detail"])

    def test_auto_sync_endpoint_uses_local_alignment_result(self) -> None:
        matches = [
            {
                "line": 0,
                "start": 0.25,
                "end": 1.15,
                "confidence": 0.93,
                "matched_text": "你来中国",
            }
        ]
        with patch(
            "app.transcribe_and_align",
            return_value={"matches": matches, "recognized_text": "第十一课你来中国"},
        ) as transcribe:
            response = self.client.post(
                "/api/align",
                files={"audio": ("dialogue.mp3", self.audio, "audio/mpeg")},
                data={
                    "request_json": json.dumps(
                        {"lines": ["大卫：你来中国"], "duration": 2},
                        ensure_ascii=False,
                    )
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["matches"], matches)
        transcribe.assert_called_once()

    def test_export_creates_clips_and_metadata(self) -> None:
        manifest = {
            "title": "课文 Lesson 1",
            "source_folder": r"H:\Chinese\Standard Course\HSK 4\hsk4_SB_B_audio",
            "duration": 2,
            "vocabulary": [
                {"hanzi": "你好", "pinyin": "ni3hao3", "definition": "hello"}
            ],
            "lines": [
                {
                    "sentence": "你好。",
                    "start": 0.1,
                    "end": 0.8,
                    "gloss": "Hello.",
                    "reading": '<span class="tone3">nǐ</span>',
                    "ruby": "<ruby>你<rt>nǐ</rt></ruby>",
                    "dictionary_gloss": "❖ you",
                    "Word": "你好",
                    "WordDef": "hello<hr>you",
                    "WordRuby": "<ruby>你<rt>nǐ</rt></ruby>",
                },
                {
                    "sentence": "再见。",
                    "start": 0.9,
                    "end": 1.7,
                    "gloss": "Goodbye.",
                },
            ],
        }
        response = self.client.post(
            "/api/export",
            files={"audio": ("11-2.mp3", self.audio, "audio/mpeg")},
            data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "hsk4_SB_B_audio-11-2-line-001.mp3",
                    "hsk4_SB_B_audio-11-2-line-002.mp3",
                    "dialogue.json",
                    "dialogue.csv",
                    "11-2.txt",
                    "11-2-vocab.txt",
                    "11-2.apkg",
                },
            )
            self.assertGreater(len(archive.read("hsk4_SB_B_audio-11-2-line-001.mp3")), 0)
            self.assertEqual(
                archive.read("11-2.txt").decode("utf-8"),
                "你好。\n再见。",
            )
            self.assertEqual(
                archive.read("11-2-vocab.txt").decode("utf-8"),
                "你好\tni3hao3\thello",
            )
            exported = json.loads(archive.read("dialogue.json"))
            self.assertEqual(exported["lines"][0]["sentence"], "你好。")
            self.assertEqual(exported["lines"][0]["gloss"], "Hello.")
            self.assertNotIn("start", exported["lines"][0])
            self.assertNotIn("end", exported["lines"][0])
            self.assertEqual(
                exported["lines"][0]["clip"],
                "hsk4_SB_B_audio-11-2-line-001.mp3",
            )
            self.assertEqual(exported["lines"][0]["reading"], '<span class="tone3">nǐ</span>')
            self.assertEqual(exported["lines"][0]["ruby"], "<ruby>你<rt>nǐ</rt></ruby>")
            self.assertEqual(exported["lines"][0]["dictionary_gloss"], "❖ you")
            self.assertEqual(exported["lines"][0]["Word"], "你好")
            self.assertEqual(exported["lines"][0]["WordDef"], "hello<hr>you")
            self.assertEqual(exported["lines"][0]["WordRuby"], "<ruby>你<rt>nǐ</rt></ruby>")
            with zipfile.ZipFile(io.BytesIO(archive.read("11-2.apkg"))) as anki_package:
                package_files = anki_package.namelist()
                self.assertIn("collection.anki2", package_files)
                media_map = json.loads(anki_package.read("media"))
                self.assertEqual(
                    set(media_map.values()),
                    {
                        "hsk4_SB_B_audio-11-2-line-001.mp3",
                        "hsk4_SB_B_audio-11-2-line-002.mp3",
                    },
                )
                self.assertEqual(
                    anki_package.read(
                        next(index for index, name in media_map.items()
                             if name == "hsk4_SB_B_audio-11-2-line-001.mp3")
                    ),
                    archive.read("hsk4_SB_B_audio-11-2-line-001.mp3"),
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    collection_path = Path(temp_dir) / "collection.anki2"
                    collection_path.write_bytes(anki_package.read("collection.anki2"))
                    collection = sqlite3.connect(collection_path)
                    try:
                        models = json.loads(
                            collection.execute("SELECT models FROM col").fetchone()[0]
                        )
                        model = next(
                            (model_id, model)
                            for model_id, model in models.items()
                            if model["name"] == "Chinese (Sentence)"
                        )
                        self.assertEqual(int(model[0]), 1582785802209)
                        model = model[1]
                        field_names = [field["name"] for field in model["flds"]]
                        self.assertEqual(
                            field_names,
                            [
                                "Hanzi",
                                "Reading",
                                "Meaning",
                                "Ruby",
                                "Sound",
                                "Q1",
                                "Q2",
                                "isProduction",
                                "Image",
                                "Gloss",
                                "Literal",
                                "Notes",
                                "Word",
                                "english",
                                "Q1 Word",
                                "Q1 Ruby",
                                "Q1 Def",
                                "Q2 Word",
                                "Q2 Ruby",
                                "Q2 Def",
                            ],
                        )
                        notes = collection.execute("SELECT flds FROM notes").fetchall()
                        self.assertEqual(len(notes), 2)
                        note_fields = [
                            dict(zip(field_names, note[0].split("\x1f")))
                            for note in notes
                        ]
                        first_note = next(fields for fields in note_fields if fields["Hanzi"] == "你好。")
                        self.assertEqual(first_note["Reading"], '<span class="tone3">nǐ</span>')
                        self.assertEqual(first_note["Meaning"], "Hello.")
                        self.assertEqual(first_note["Ruby"], "<ruby>你<rt>nǐ</rt></ruby>")
                        self.assertEqual(
                            first_note["Sound"],
                            "[sound:hsk4_SB_B_audio-11-2-line-001.mp3]",
                        )
                        self.assertEqual(first_note["Q1"], "<b>你好</b>。")
                        self.assertEqual(first_note["Word"], "你好")
                        self.assertEqual(first_note["english"], "❖ you")
                        self.assertEqual(first_note["Q1 Word"], "你好")
                        self.assertEqual(first_note["Q1 Ruby"], "<ruby>你<rt>nǐ</rt></ruby>")
                        self.assertEqual(first_note["Q1 Def"], "hello<hr>you")
                        self.assertEqual(first_note["Q2"], "")
                        second_note = next(fields for fields in note_fields if fields["Hanzi"] == "再见。")
                        self.assertEqual(second_note["Q1"], "再见。")
                        self.assertEqual(collection.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 4)
                    finally:
                        collection.close()
            csv_text = archive.read("dialogue.csv").decode("utf-8-sig")
            csv_header = csv_text.splitlines()[0]
            self.assertIn("Word,WordDef,WordRuby", csv_header)
            self.assertNotIn("start", csv_header)
            self.assertNotIn("end", csv_header)
            self.assertIn("hsk4_SB_B_audio-11-2-line-001.mp3", csv_text)
            self.assertTrue(archive.read("dialogue.csv").startswith(b"\xef\xbb\xbf"))

    def test_export_rejects_line_past_audio_duration(self) -> None:
        manifest = {
            "title": "Lesson",
            "duration": 1,
            "lines": [
                {"sentence": "你好。", "start": 0.2, "end": 1.2, "gloss": ""}
            ],
        }
        response = self.client.post(
            "/api/export",
            files={"audio": ("dialogue.mp3", self.audio, "audio/mpeg")},
            data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("audio duration", response.json()["detail"])

    def test_export_omits_vocabulary_file_when_no_vocabulary_is_provided(self) -> None:
        manifest = {
            "title": "Lesson",
            "duration": 2,
            "lines": [
                {"sentence": "你好。", "start": 0.1, "end": 0.8, "gloss": ""}
            ],
        }
        response = self.client.post(
            "/api/export",
            files={"audio": ("11-2.mp3", self.audio, "audio/mpeg")},
            data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("11-2.txt", archive.namelist())
            self.assertNotIn("11-2-vocab.txt", archive.namelist())
            self.assertIn("11-2.apkg", archive.namelist())


if __name__ == "__main__":
    unittest.main()
