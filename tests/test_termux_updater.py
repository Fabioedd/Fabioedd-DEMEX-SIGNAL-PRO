import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from termux import termux_updater as updater


class UpdaterSafetyTests(unittest.TestCase):
    def test_sha256_matches_known_value(self):
        self.assertEqual(updater.sha256(b"abc"), hashlib.sha256(b"abc").hexdigest())

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "bad.tar.gz"
            destination = root / "destination"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../outside.txt")
                payload = b"bad"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(RuntimeError):
                updater.safe_extract(archive_path, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_safe_extract_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "link.tar.gz"
            destination = root / "destination"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("demex/escape")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                archive.addfile(info)
            with self.assertRaises(RuntimeError):
                updater.safe_extract(archive_path, destination)

    def test_atomic_switch_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = Path(temp) / ".demex"
            versions = manager / "versions"
            versions.mkdir(parents=True)
            (versions / "v1").mkdir()
            (versions / "v2").mkdir()
            current = manager / "current"
            current.symlink_to(Path("versions") / "v1")
            with patch.object(updater, "MANAGER", manager), patch.object(updater, "CURRENT", current):
                previous = updater.atomic_current_switch("v2")
                self.assertEqual(os.readlink(current), "versions/v2")
                updater.restore_current(previous)
                self.assertEqual(os.readlink(current), "versions/v1")

    def test_stale_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "update.lock"
            lock.mkdir()
            (lock / "owner").write_text("999999999", encoding="ascii")
            with patch.object(updater, "_pid_is_updater", return_value=False):
                updater.acquire_lock(lock)
            self.assertEqual((lock / "owner").read_text(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
