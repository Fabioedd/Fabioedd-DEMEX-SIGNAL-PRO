import hashlib
import tempfile
import tarfile
import unittest
from pathlib import Path

from termux.termux_updater import safe_extract, sha256


class UpdaterSafetyTests(unittest.TestCase):
    def test_sha256_matches_known_value(self):
        self.assertEqual(
            sha256(b"abc"),
            hashlib.sha256(b"abc").hexdigest(),
        )

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "bad.tar.gz"
            outside = root / "outside.txt"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../outside.txt")
                payload = b"bad"
                info.size = len(payload)
                import io
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(RuntimeError):
                safe_extract(archive_path, root / "destination")
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
