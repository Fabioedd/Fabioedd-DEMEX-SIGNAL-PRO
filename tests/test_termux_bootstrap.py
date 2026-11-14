import hashlib
import io
import re
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BOOTSTRAP = Path(__file__).resolve().parents[1] / "termux" / "demex-bootstrap.sh"


class FakeResponse:
    def __init__(self, *, url=None, data=b""):
        self.url = url
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self):
        return self.data


def recovery_source():
    source = BOOTSTRAP.read_text(encoding="utf-8")
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", source, re.DOTALL)
    if not match:
        raise AssertionError("Bloco Python de recuperação não encontrado.")
    return match.group(1)


def make_archive():
    output = io.BytesIO()
    payload = b"# updater de teste\n"
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo("demex/termux/termux_updater.py")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


class TermuxBootstrapTests(unittest.TestCase):
    def test_valid_updater_does_not_recover_bootstrapper_on_every_cycle(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(
            'if [ ! -s "$UPDATER" ] || ! python3 -m py_compile "$UPDATER" >/dev/null 2>&1; then',
            source,
        )
        self.assertNotIn('if [ "$COMMAND" != "status"', source)

    def test_recovery_uses_github_release_redirect_and_validates_checksum(self):
        archive = make_archive()
        checksum = f"{hashlib.sha256(archive).hexdigest()}  demex-source.tar.gz\n".encode()
        responses = [
            FakeResponse(url="https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO/releases/tag/v1.0.3"),
            FakeResponse(data=archive),
            FakeResponse(data=checksum),
        ]
        with tempfile.TemporaryDirectory() as temp:
            updater = Path(temp) / ".demex" / "termux_updater.py"
            version = Path(temp) / ".demex" / "updater-release"
            original_argv = sys.argv
            try:
                sys.argv = ["bootstrap-recovery", str(updater), str(version)]
                with patch("urllib.request.urlopen", side_effect=responses) as open_url:
                    exec(compile(recovery_source(), str(BOOTSTRAP), "exec"), {"__name__": "__main__"})
            finally:
                sys.argv = original_argv
            self.assertEqual(updater.read_bytes(), b"# updater de teste\n")
            self.assertEqual(version.read_text(encoding="utf-8"), "v1.0.3\n")
            first_url = open_url.call_args_list[0].args[0].full_url
            self.assertEqual(
                first_url,
                "https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO/releases/latest",
            )
            self.assertNotIn("api.github.com", first_url)

    def test_recovery_rejects_redirect_outside_repository_release(self):
        with tempfile.TemporaryDirectory() as temp:
            original_argv = sys.argv
            try:
                sys.argv = ["bootstrap-recovery", str(Path(temp) / "updater.py"), str(Path(temp) / "version")]
                with patch(
                    "urllib.request.urlopen",
                    return_value=FakeResponse(url="https://github.com/login"),
                ) as open_url:
                    with self.assertRaises(SystemExit):
                        exec(compile(recovery_source(), str(BOOTSTRAP), "exec"), {"__name__": "__main__"})
            finally:
                sys.argv = original_argv
            self.assertEqual(open_url.call_count, 1)


if __name__ == "__main__":
    unittest.main()
