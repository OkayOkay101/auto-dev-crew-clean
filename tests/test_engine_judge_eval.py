"""Unit tests for the judge harness helpers (no live engine calls)."""
import unittest

from scripts import engine_judge_eval as ev


class RedactTests(unittest.TestCase):
    def test_long_token_is_redacted(self):
        self.assertEqual(ev.redact("key=AQ.abcdef1234567890XYZ ok"), "key=<redacted> ok")

    def test_short_words_kept(self):
        self.assertEqual(ev.redact("สวัสดี OK 42"), "สวัสดี OK 42")


class ParseVerdictTests(unittest.TestCase):
    def test_plain_json(self):
        v = ev.parse_verdict('{"score": 4, "pass": true, "reason": "ดี"}')
        self.assertEqual((v["score"], v["pass"]), (4, True))

    def test_json_surrounded_by_prose_and_braces(self):
        raw = 'ผลการประเมิน {ตัวอย่าง} : {"score": 2, "pass": false, "reason": "x"} จบ'
        v = ev.parse_verdict(raw)
        self.assertEqual(v["score"], 2)

    def test_pass_defaults_from_score(self):
        self.assertTrue(ev.parse_verdict('{"score": 5}')["pass"])
        self.assertFalse(ev.parse_verdict('{"score": 3}')["pass"])

    def test_garbage_returns_none(self):
        self.assertIsNone(ev.parse_verdict("no json here"))
        self.assertIsNone(ev.parse_verdict('{"score": "abc"}'))


if __name__ == "__main__":
    unittest.main()
