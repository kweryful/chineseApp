import unittest

from alignment import align_lines_to_words, normalize_text, strip_speaker_label


class AlignmentTests(unittest.TestCase):
    def test_normalizes_chinese_and_removes_speaker_labels(self) -> None:
        self.assertEqual(strip_speaker_label("大卫：你好吗？"), "你好吗？")
        self.assertEqual(normalize_text("你好吗？ Hello!"), "你好吗hello")

    def test_matches_spoken_heading_after_unspoken_intro(self) -> None:
        heading = "马克介绍自己学习汉语的方法"
        lines = [
            heading,
            "大卫：你来中国才一年，汉语就说得这么流利，真厉害！",
            "马克：谢谢！其实我的语法不太好，很多句子说得都不太准确。",
        ]
        transcript = (
            "第十一课马克介绍自己学习汉语的方法"
            "你来中国才一年汉语就说得这么流利真厉害"
            "谢谢其实我的语法不太好很多句子说得都不太准确"
        )
        words = [
            (character, index * 0.1, (index + 1) * 0.1)
            for index, character in enumerate(transcript)
        ]

        matches = align_lines_to_words(lines, words, len(transcript) * 0.1)

        self.assertEqual(matches[0]["matched_text"], normalize_text(heading))
        self.assertAlmostEqual(matches[0]["start"], 0.4)
        self.assertGreater(matches[1]["start"], 1.5)
        self.assertGreater(matches[1]["confidence"], 0.9)
        self.assertGreater(matches[2]["start"], matches[1]["start"])
        self.assertEqual(matches[2]["confidence"], 1.0)

    def test_unspoken_heading_does_not_block_dialogue(self) -> None:
        heading = "马克介绍自己学习汉语的方法"
        dialogue = "你来中国才一年，汉语就说得这么流利，真厉害！"
        transcript = normalize_text(dialogue)
        words = [
            (character, index * 0.1, (index + 1) * 0.1)
            for index, character in enumerate(transcript)
        ]

        matches = align_lines_to_words([heading, dialogue], words, len(transcript) * 0.1)

        self.assertIsNone(matches[0]["start"])
        self.assertEqual(matches[0]["matched_text"], "")
        self.assertIsNotNone(matches[1]["start"])

    def test_unmatched_line_does_not_block_later_dialogue(self) -> None:
        words = [("你好", 1.0, 1.5), ("再见", 2.0, 2.5)]
        matches = align_lines_to_words(["没听说过的一句话", "再见"], words, 3)

        self.assertIsNone(matches[0]["start"])
        self.assertAlmostEqual(matches[1]["start"], 1.5)
        self.assertGreater(matches[1]["end"], matches[1]["start"])

    def test_splits_multi_character_word_timestamps_between_lines(self) -> None:
        matches = align_lines_to_words(["你好", "再见"], [("你好再见", 1.0, 5.0)], 6)

        self.assertAlmostEqual(matches[0]["start"], 0.96)
        self.assertAlmostEqual(matches[0]["end"], 3.13)
        self.assertAlmostEqual(matches[1]["start"], 3.13)
        self.assertAlmostEqual(matches[1]["end"], 5.13)

    def test_adds_clip_margin_without_crossing_previous_speech(self) -> None:
        matches = align_lines_to_words(
            ["然后写在本子上。", "有空儿就拿出来复习一下，"],
            [
                ("然后写在本子上", 64.53, 66.277),
                ("有空儿就拿出来复习一下", 67.58, 69.22),
            ],
            70.0,
        )

        self.assertAlmostEqual(matches[1]["start"], 67.03)
        self.assertAlmostEqual(matches[1]["end"], 69.35)

    def test_trims_each_adjacent_clip_to_edges_of_waveform_silence(self) -> None:
        sample_rate = 1000
        samples = [12000] * (4 * sample_rate)
        for index in range(2200, 2400):
            samples[index] = 0

        matches = align_lines_to_words(
            ["前一句。", "然后写在本子上。"],
            [("前一句", 1.0, 2.0), ("然后写在本子上", 2.5, 3.5)],
            4.0,
            samples,
            sample_rate,
        )

        self.assertAlmostEqual(matches[0]["end"], 2.2)
        self.assertAlmostEqual(matches[1]["start"], 2.4)

    def test_keeps_speech_timing_when_gap_has_no_quiet_space(self) -> None:
        sample_rate = 1000
        samples = [12000] * (4 * sample_rate)

        matches = align_lines_to_words(
            ["前一句。", "然后写在本子上。"],
            [("前一句", 1.0, 2.0), ("然后写在本子上", 2.5, 3.5)],
            4.0,
            samples,
            sample_rate,
        )

        self.assertAlmostEqual(matches[0]["end"], 2.13)
        self.assertAlmostEqual(matches[1]["start"], 2.46)

    def test_limits_start_padding_when_waveform_has_no_detectable_silence(self) -> None:
        sample_rate = 1000
        samples = [12000] * (61 * sample_rate)

        matches = align_lines_to_words(
            ["前一句。", "刚开始肯定有困难。"],
            [("前一句", 56.0, 56.91), ("刚开始肯定有困难", 57.546, 59.856)],
            61.0,
            samples,
            sample_rate,
        )

        self.assertAlmostEqual(matches[1]["start"], 57.506)

    def test_trims_start_and_end_of_line_using_surrounding_silences(self) -> None:
        sample_rate = 1000
        samples = [12000] * (24 * sample_rate)
        for start, end in ((17400, 18600), (20550, 20640)):
            samples[start:end] = [0] * (end - start)

        matches = align_lines_to_words(
            ["前一句。", "你来中国才一年。", "汉语就说得这么流利。"],
            [
                ("前一句", 16.5, 16.8),
                ("你来中国才一年", 18.688, 20.547),
                ("汉语就说得这么流利", 20.64, 22.53),
            ],
            24.0,
            samples,
            sample_rate,
        )

        self.assertAlmostEqual(matches[1]["start"], 18.6)
        self.assertGreaterEqual(matches[1]["end"], 20.55)
        self.assertLess(matches[1]["end"], 20.56)
        self.assertGreater(matches[2]["start"], 20.63)
        self.assertLessEqual(matches[2]["start"], 20.64)
        self.assertLess(matches[1]["end"], matches[2]["start"])

    def test_line_boundary_does_not_consume_next_sentence_start(self) -> None:
        first = "平时多交一些中国朋友，经常和他们聊天儿，听说能力自然就能得到很大的提高。"
        second = "另外，我建议你坚持看中文报纸，这样能学到很多新词语。"
        transcript = (
            "平时多交一些中国朋友经常和他们聊天听说能力自然就能得到很大的提高"
            "另外我建议你坚持看中文报纸这样能学到很多新词语"
        )

        matches = align_lines_to_words(
            [first, second],
            [(transcript, 37.0, 53.0)],
            53.0,
        )

        self.assertNotEqual(matches[0]["matched_text"][-1], "另")
        self.assertTrue(matches[1]["matched_text"].startswith("另外"))
        self.assertLessEqual(matches[0]["end"], matches[1]["start"])

    def test_reports_speech_pause_between_comma_separated_clauses(self) -> None:
        matches = align_lines_to_words(
            ["其实我的语法不太好，", "很多句子说得都不太准确。"],
            [
                ("其实我的语法不太好", 1.0, 2.0),
                ("很多句子说得都不太准确", 2.5, 4.0),
            ],
            5.0,
        )

        self.assertAlmostEqual(matches[0]["pause_after"], 0.5)
        self.assertIsNone(matches[1]["pause_after"])


if __name__ == "__main__":
    unittest.main()
