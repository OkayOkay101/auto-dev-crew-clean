"""Password login primitives for the control GUI: hashing, sessions, rate limit, set-password CLI."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auto_dev_crew import auth


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class PasswordHashTests(unittest.TestCase):
    def test_correct_password_verifies(self):
        stored = auth.hash_password("correct horse 42")
        self.assertTrue(auth.verify_password("correct horse 42", stored))

    def test_wrong_password_is_rejected(self):
        stored = auth.hash_password("correct horse 42")
        self.assertFalse(auth.verify_password("correct horse 43", stored))
        self.assertFalse(auth.verify_password("", stored))

    def test_same_password_gets_different_salt_each_time(self):
        self.assertNotEqual(auth.hash_password("same-pass-1"), auth.hash_password("same-pass-1"))

    def test_stored_value_does_not_contain_plaintext(self):
        self.assertNotIn("plain-secret-99", auth.hash_password("plain-secret-99"))

    def test_malformed_stored_value_is_rejected_without_raising(self):
        for bad in ("", "not-a-hash", "scrypt$x$y$z$$", "md5$abc$def"):
            self.assertFalse(auth.verify_password("anything", bad), bad)

    def test_empty_password_cannot_be_hashed(self):
        with self.assertRaises(ValueError):
            auth.hash_password("")


class SessionTests(unittest.TestCase):
    def test_new_session_is_valid_and_tokens_are_unique(self):
        store = auth.SessionStore(ttl_seconds=60, clock=FakeClock())
        a, b = store.create(), store.create()
        self.assertNotEqual(a, b)
        self.assertTrue(store.is_valid(a))
        self.assertTrue(store.is_valid(b))

    def test_session_expires_after_ttl(self):
        clock = FakeClock()
        store = auth.SessionStore(ttl_seconds=60, clock=clock)
        token = store.create()
        clock.advance(59)
        self.assertTrue(store.is_valid(token))
        clock.advance(2)
        self.assertFalse(store.is_valid(token))

    def test_revoked_session_is_invalid(self):
        store = auth.SessionStore(ttl_seconds=60, clock=FakeClock())
        token = store.create()
        store.revoke(token)
        self.assertFalse(store.is_valid(token))

    def test_missing_or_unknown_token_is_invalid(self):
        store = auth.SessionStore(ttl_seconds=60, clock=FakeClock())
        store.create()
        for token in (None, "", "guessed-token"):
            self.assertFalse(store.is_valid(token))


class LoginLimiterTests(unittest.TestCase):
    def test_locks_after_max_failures_for_that_key_only(self):
        limiter = auth.LoginLimiter(max_failures=3, window_seconds=900, lock_seconds=900, clock=FakeClock())
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        self.assertTrue(limiter.is_locked("1.2.3.4"))
        self.assertFalse(limiter.is_locked("5.6.7.8"))

    def test_below_threshold_is_not_locked(self):
        limiter = auth.LoginLimiter(max_failures=3, window_seconds=900, lock_seconds=900, clock=FakeClock())
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        self.assertFalse(limiter.is_locked("1.2.3.4"))

    def test_lock_lifts_after_lock_seconds(self):
        clock = FakeClock()
        limiter = auth.LoginLimiter(max_failures=2, window_seconds=900, lock_seconds=600, clock=clock)
        limiter.record_failure("ip")
        limiter.record_failure("ip")
        self.assertTrue(limiter.is_locked("ip"))
        clock.advance(601)
        self.assertFalse(limiter.is_locked("ip"))

    def test_success_clears_failure_count(self):
        limiter = auth.LoginLimiter(max_failures=3, window_seconds=900, lock_seconds=900, clock=FakeClock())
        limiter.record_failure("ip")
        limiter.record_failure("ip")
        limiter.record_success("ip")
        limiter.record_failure("ip")
        self.assertFalse(limiter.is_locked("ip"))

    def test_old_failures_outside_window_do_not_count(self):
        clock = FakeClock()
        limiter = auth.LoginLimiter(max_failures=3, window_seconds=100, lock_seconds=900, clock=clock)
        limiter.record_failure("ip")
        limiter.record_failure("ip")
        clock.advance(101)
        limiter.record_failure("ip")
        self.assertFalse(limiter.is_locked("ip"))


class PasswordFileTests(unittest.TestCase):
    def test_missing_file_loads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(auth.load_password_hash(Path(tmp) / "auth.json"))

    def test_saved_hash_round_trips_and_file_holds_no_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            auth.save_password_hash(path, auth.hash_password("round-trip-7"))
            stored = auth.load_password_hash(path)
            self.assertTrue(auth.verify_password("round-trip-7", stored))
            self.assertNotIn("round-trip-7", path.read_text(encoding="utf-8"))


class SetPasswordCliTests(unittest.TestCase):
    def test_matching_entries_write_a_verifiable_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            answers = iter(["cli-pass-123", "cli-pass-123"])
            rc = auth.set_password_cli(path, prompt=lambda _msg: next(answers))
            self.assertEqual(rc, 0)
            self.assertTrue(auth.verify_password("cli-pass-123", auth.load_password_hash(path)))

    def test_mismatched_entries_write_nothing_and_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            answers = iter(["one-pass-111", "two-pass-222"])
            rc = auth.set_password_cli(path, prompt=lambda _msg: next(answers))
            self.assertNotEqual(rc, 0)
            self.assertFalse(path.exists())

    def test_too_short_password_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            answers = iter(["abc", "abc"])
            rc = auth.set_password_cli(path, prompt=lambda _msg: next(answers))
            self.assertNotEqual(rc, 0)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
