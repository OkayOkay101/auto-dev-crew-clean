import os
import sys
import time
import threading
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew.locks import file_lock, locked_json_read, locked_json_write, LockTimeout


class TestLocks(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "scratch"
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_file_lock_mutual_exclusion(self):
        lock_file = self.test_dir / "test.lock"
        counter_file = self.test_dir / "counter.txt"
        counter_file.write_text("0", encoding="utf-8")

        def worker():
            for _ in range(10):
                with file_lock(lock_file, timeout=10.0):
                    val = int(counter_file.read_text(encoding="utf-8"))
                    time.sleep(0.01)
                    counter_file.write_text(str(val + 1), encoding="utf-8")

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(counter_file.read_text(encoding="utf-8"), "30")

    def test_locked_json_roundtrip(self):
        path = self.test_dir / "state.json"
        data = {"a": 1, "b": "ภาษาไทย", "list": [1, 2, 3]}
        locked_json_write(path, data)
        read_back = locked_json_read(path)
        self.assertEqual(read_back, data)

    def test_locked_json_read_default_on_missing(self):
        path = self.test_dir / "missing.json"
        self.assertEqual(locked_json_read(path, default=[]), [])
        self.assertIsNone(locked_json_read(path))

    def test_lock_reentrancy(self):
        lock_file = self.test_dir / "reentrant.lock"
        with file_lock(lock_file, timeout=1.0):
            with file_lock(lock_file, timeout=1.0):
                self.assertTrue(lock_file.exists())

    def test_lock_timeout(self):
        lock_file = self.test_dir / "timeout.lock"
        err_holder = []

        def other_thread():
            try:
                with file_lock(lock_file, timeout=0.1):
                    pass
            except LockTimeout as exc:
                err_holder.append(exc)

        with file_lock(lock_file, timeout=2.0):
            t = threading.Thread(target=other_thread)
            t.start()
            t.join()

        self.assertEqual(len(err_holder), 1)
        self.assertIsInstance(err_holder[0], LockTimeout)

    def test_stale_lock_recovery(self):
        lock_file = self.test_dir / "stale.lock"
        lock_file.write_text("dummy", encoding="utf-8")
        # Set modification time back by 1000 seconds
        old_time = time.time() - 1000
        os.utime(lock_file, (old_time, old_time))

        # Should recover stale lock if stale_seconds=10.0
        with file_lock(lock_file, timeout=2.0, stale_seconds=10.0):
            self.assertTrue(lock_file.exists())

    def test_corrupt_json_is_quarantined(self):
        path = self.test_dir / "corrupt_hist.json"
        path.write_text("{ not valid json", encoding="utf-8")

        result = locked_json_read(path, default=[])

        self.assertEqual(result, [])
        self.assertFalse(path.exists())
        quarantined = list(self.test_dir.glob("corrupt_hist.json.corrupt-*"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"), "{ not valid json")

    def test_locked_json_write_fsyncs_before_replace(self):
        import unittest.mock as mock
        path = self.test_dir / "fsync.json"
        with mock.patch("auto_dev_crew.locks.os.fsync", wraps=os.fsync) as fsync_spy:
            locked_json_write(path, {"a": 1})
        self.assertTrue(fsync_spy.called)
        self.assertEqual(locked_json_read(path), {"a": 1})

    def test_held_lock_not_broken_after_stale_window(self):
        import subprocess
        lock_file = self.test_dir / "held.lock"
        script = "\n".join([
            "import sys",
            "sys.path.insert(0, sys.argv[1])",
            "from auto_dev_crew.locks import file_lock, LockTimeout",
            "try:",
            "    with file_lock(sys.argv[2], timeout=0.5, stale_seconds=0.001):",
            "        print('ACQUIRED')",
            "except LockTimeout:",
            "    print('TIMEOUT')",
        ])
        with file_lock(lock_file, timeout=2.0):
            old_time = time.time() - 3600
            os.utime(lock_file, (old_time, old_time))
            res = subprocess.run(
                [sys.executable, "-c", script, str(ROOT), str(lock_file)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertIn("TIMEOUT", res.stdout, res.stderr)
            self.assertTrue(lock_file.exists())

    def test_atomic_write_text_replaces_content_and_leaves_no_tmp(self):
        from auto_dev_crew.locks import atomic_write_text
        path = self.test_dir / "cfg.yaml"
        path.write_text("old: 1\n", encoding="utf-8")

        atomic_write_text(path, "new: ภาษาไทย\n")

        self.assertEqual(path.read_text(encoding="utf-8"), "new: ภาษาไทย\n")
        leftovers = [p.name for p in self.test_dir.iterdir() if ".tmp" in p.name]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
