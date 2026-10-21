import io
import json
import subprocess
import unittest
import zipfile
from unittest.mock import patch

import imageio_ffmpeg
from fastapi.testclient import TestClient

from app import app


class DialogueAppTests(unittest.TestCase):
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
            "duration": 2,
            "lines": [
                {"sentence": "你好。", "start": 0.1, "end": 0.8, "gloss": "Hello."},
                {"sentence": "再见。", "start": 0.9, "end": 1.7, "gloss": "Goodbye."},
            ],
        }
        response = self.client.post(
            "/api/export",
            files={"audio": ("dialogue.mp3", self.audio, "audio/mpeg")},
            data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"line-001.mp3", "line-002.mp3", "dialogue.json", "dialogue.csv"},
            )
            self.assertGreater(len(archive.read("line-001.mp3")), 0)
            exported = json.loads(archive.read("dialogue.json"))
            self.assertEqual(exported["lines"][0]["sentence"], "你好。")
            self.assertEqual(exported["lines"][0]["gloss"], "Hello.")
            self.assertTrue(archive.read("dialogue.csv").startswith(b"\xef\xbb\xbf"))

    def test_export_rejects_line_past_audio_duration(self) -> None:
        manifest = {
            "title": "Lesson",
            "duration": 1,
            "lines": [{"sentence": "你好。", "start": 0.2, "end": 1.2, "gloss": ""}],
        }
        response = self.client.post(
            "/api/export",
            files={"audio": ("dialogue.mp3", self.audio, "audio/mpeg")},
            data={"manifest": json.dumps(manifest, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("audio duration", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
