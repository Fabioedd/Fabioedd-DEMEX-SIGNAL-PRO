import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from termux import termux_updater as updater


def make_release_archive():
    buffer = io.BytesIO()
    files = {
        "demex/main.py": b"print('DEMEX')\n",
        "demex/settings.json": b'{"scan_interval_seconds": 2, "entry_cooldown_seconds": 60}\n',
        "demex/requirements.txt": b"\n",
        "demex/demex.sh": b"#!/bin/bash\n",
        "demex/telegram_control.py": b"print('Telegram control')\n",
        "demex/strategies/my_strategy.py": b"def get_intrabar_signal(*args): return None\n",
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class UpdaterSafetyTests(unittest.TestCase):
    def test_same_release_recovers_missing_telegram_listener(self):
        with tempfile.TemporaryDirectory() as temp:
            version = Path(temp) / "v1"
            version.mkdir()
            with patch.object(updater, "start_telegram_listener", return_value=4321) as start:
                pid = updater.ensure_telegram_listener(version, [])
            self.assertEqual(pid, 4321)
            start.assert_called_once_with(version)

    def test_same_release_keeps_listener_on_active_version(self):
        with tempfile.TemporaryDirectory() as temp:
            version = Path(temp) / "v1"
            version.mkdir()
            script = version / "telegram_control.py"
            script.touch()
            listener = {"pid": 1234, "script": str(script)}
            with patch.object(updater, "start_telegram_listener") as start, \
                 patch.object(updater, "stop_telegram_listener") as stop:
                pid = updater.ensure_telegram_listener(version, [listener])
            self.assertEqual(pid, 1234)
            start.assert_not_called()
            stop.assert_not_called()

    def test_latest_release_resolves_redirect_without_rest_api(self):
        response = SimpleNamespace(
            geturl=lambda: "https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO/releases/tag/v1.0.2"
        )
        with patch.object(updater.urllib.request, "urlopen", return_value=response) as open_url:
            tag, assets = updater.latest_release()
        self.assertEqual(tag, "v1.0.2")
        self.assertEqual(
            assets["demex-source.tar.gz"],
            "https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO/releases/download/v1.0.2/demex-source.tar.gz",
        )
        self.assertTrue(assets["SHA256SUMS"].endswith("/v1.0.2/SHA256SUMS"))
        self.assertNotIn("api.github.com", open_url.call_args.args[0].full_url)

    def test_latest_release_rejects_unexpected_redirect(self):
        response = SimpleNamespace(geturl=lambda: "https://github.com/login")
        with patch.object(updater.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                updater.latest_release()

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

    def _run_update(self, temp, *, robot=False, install_error=None, test_error=None, no_space=False, network_error=None, legacy=False, listeners=None):
        manager = Path(temp) / ".demex"
        versions = manager / "versions"
        shared = manager / "shared"
        versions.mkdir(parents=True)
        shared.mkdir()
        current = manager / "current"
        old_version = versions / "v1"
        old_version.mkdir()
        current.symlink_to(Path("versions") / "v1")
        project = Path(temp) / "Fabioedd-DEMEX-SIGNAL-PRO"
        if legacy:
            project.mkdir()
            (project / ".env").write_text("TOKEN=local-secret\n")
            (project / "settings.json").write_text('{"scan_interval_seconds":2,"entry_cooldown_seconds":60}\n')
        archive = make_release_archive()
        checksum = f"{hashlib.sha256(archive).hexdigest()}  demex-source.tar.gz\n".encode()
        old_cwd = Path.cwd()
        try:
            with patch.multiple(
                updater,
                MANAGER=manager, VERSIONS=versions, CURRENT=current, SHARED=shared,
                PROJECT_LINK=project, LOG=Path(temp) / "updater.log",
            ), patch.object(updater, "robot_is_running", return_value=robot), \
                 patch.object(updater, "legacy_sync_is_running", return_value=False), \
                 patch.object(updater, "find_telegram_listeners", return_value=listeners or []), \
                 patch.object(updater, "stop_telegram_listener") as stop_listener, \
                 patch.object(updater, "start_telegram_listener", return_value=4321) as start_listener, \
                 patch.object(updater, "latest_release", return_value=("v2", {"demex-source.tar.gz":"archive", "SHA256SUMS":"sums"})), \
                 patch.object(updater, "request_bytes", side_effect=network_error or [archive, checksum]), \
                 patch.object(updater.shutil, "disk_usage", return_value=SimpleNamespace(free=0 if no_space else 2 * 1024**3)):
                def install(version_dir):
                    if install_error:
                        raise install_error
                    vpy = version_dir / ".venv" / "bin" / "python"
                    vpy.parent.mkdir(parents=True)
                    vpy.write_text("#!/bin/sh\n")
                    return vpy
                with patch.object(updater, "install_dependencies", side_effect=install), \
                     patch.object(updater, "validate_version", side_effect=test_error), \
                     patch.object(updater, "prune_versions"):
                    result = updater.update()
            return result, current, project, shared, manager, stop_listener.call_count, start_listener.call_count
        finally:
            os.chdir(old_cwd)

    def test_no_internet_keeps_previous_version(self):
        with tempfile.TemporaryDirectory() as temp:
            result, current, *_ = self._run_update(
                temp, network_error=urllib.error.URLError("offline")
            )
            self.assertEqual(result, 1)
            self.assertEqual(os.readlink(current), "versions/v1")

    def test_low_storage_keeps_previous_version(self):
        with tempfile.TemporaryDirectory() as temp:
            result, current, *_ = self._run_update(temp, no_space=True)
            self.assertEqual(result, 1)
            self.assertEqual(os.readlink(current), "versions/v1")

    def test_dependency_failure_keeps_previous_version(self):
        with tempfile.TemporaryDirectory() as temp:
            failure = subprocess.CalledProcessError(1, ["pip", "install"])
            result, current, *_ = self._run_update(temp, install_error=failure)
            self.assertEqual(result, 1)
            self.assertEqual(os.readlink(current), "versions/v1")

    def test_test_failure_keeps_previous_version(self):
        with tempfile.TemporaryDirectory() as temp:
            failure = subprocess.CalledProcessError(1, ["unittest"])
            result, current, *_ = self._run_update(temp, test_error=failure)
            self.assertEqual(result, 1)
            self.assertEqual(os.readlink(current), "versions/v1")

    def test_running_robot_blocks_update(self):
        with tempfile.TemporaryDirectory() as temp:
            result, current, *_ = self._run_update(temp, robot=True)
            self.assertEqual(result, 2)
            self.assertEqual(os.readlink(current), "versions/v1")


    def test_active_versioned_telegram_listener_is_restarted_after_update(self):
        with tempfile.TemporaryDirectory() as temp:
            old_root = str(Path(temp) / ".demex" / "versions" / "v1")
            result, current, *_rest, stopped, started = self._run_update(
                temp, listeners=[{"pid": 1234, "cwd": old_root, "script": str(Path(old_root) / "telegram_control.py")}]
            )
            self.assertEqual(result, 0)
            self.assertEqual(os.readlink(current), "versions/v2")
            self.assertEqual(stopped, 1)
            self.assertEqual(started, 1)


    def test_unrelated_telegram_listener_is_never_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            unrelated = str(Path(temp) / "another-project" / "telegram_control.py")
            result, current, *_rest, stopped, started = self._run_update(
                temp, listeners=[{
                    "pid": 9876,
                    "cwd": str(Path(temp) / "another-project"),
                    "script": unrelated,
                }]
            )
            self.assertEqual(result, 0)
            self.assertEqual(os.readlink(current), "versions/v2")
            self.assertEqual(stopped, 0)
            self.assertEqual(started, 0)

    def test_legacy_telegram_listener_blocks_first_migration_without_stopping_robot(self):
        with tempfile.TemporaryDirectory() as temp:
            result, current, project, *_ = self._run_update(
                temp, legacy=True,
                listeners=[{
                    "pid": 2345,
                    "cwd": str(Path(temp) / "Fabioedd-DEMEX-SIGNAL-PRO"),
                    "script": str(Path(temp) / "Fabioedd-DEMEX-SIGNAL-PRO" / "telegram_control.py"),
                }],
            )
            self.assertEqual(result, 2)
            self.assertEqual(os.readlink(current), "versions/v1")
            self.assertTrue(project.is_dir())
            self.assertFalse(project.is_symlink())

    def test_successful_migration_preserves_configuration_and_switches_version(self):
        with tempfile.TemporaryDirectory() as temp:
            result, current, project, shared, manager, *_ = self._run_update(temp, legacy=True)
            self.assertEqual(result, 0)
            self.assertEqual(os.readlink(current), "versions/v2")
            self.assertTrue(project.is_symlink())
            self.assertEqual((shared / ".env").read_text(), "TOKEN=local-secret\n")
            self.assertTrue((shared / "settings.json").is_file())
            self.assertTrue((current / ".env").is_symlink())
            self.assertTrue((current / "settings.json").is_symlink())
            self.assertTrue((manager / "legacy").is_dir())


if __name__ == "__main__":
    unittest.main()
