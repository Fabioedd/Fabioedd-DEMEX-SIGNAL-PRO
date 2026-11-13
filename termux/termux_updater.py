#!/usr/bin/env python3
"""Atualizador transacional do DEMEX para Android/Termux.

Instala somente assets de GitHub Releases cujo SHA256 confere.
Nunca inicia, para ou reinicia o robô.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY = "Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO"
API_LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
HOME = Path.home()
MANAGER = HOME / ".demex"
VERSIONS = MANAGER / "versions"
CURRENT = MANAGER / "current"
PROJECT_LINK = HOME / "Fabioedd-DEMEX-SIGNAL-PRO"
SHARED = MANAGER / "shared"
LOG = HOME / "DEMEX_AUTO_UPDATE.log"
KEEP_RELEASES = 3
REQUIRED = ("main.py", "settings.json", "requirements.txt", "demex.sh", "strategies/my_strategy.py")


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def request_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DEMEX-Termux-Updater", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_release() -> tuple[str, dict[str, str]]:
    payload = json.loads(request_bytes(API_LATEST).decode("utf-8"))
    tag = str(payload.get("tag_name", "")).strip()
    if not tag or payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("O GitHub não retornou uma release estável válida.")
    assets = {
        str(item.get("name")): str(item.get("browser_download_url"))
        for item in payload.get("assets", [])
        if item.get("name") and item.get("browser_download_url")
    }
    if "demex-source.tar.gz" not in assets or "SHA256SUMS" not in assets:
        raise RuntimeError("A release não contém o pacote e o arquivo SHA256 obrigatórios.")
    return tag, assets


def sha256(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def safe_extract(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            candidate = (root / member.name).resolve()
            if candidate != root and root not in candidate.parents:
                raise RuntimeError(f"Pacote contém caminho inválido: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError(f"Pacote contém tipo de arquivo não permitido: {member.name}")
        archive.extractall(destination, members=members)


def robot_is_running() -> bool:
    managed_root = str(MANAGER.resolve())
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            cwd = str((proc / "cwd").resolve())
            state_text = (proc / "status").read_text(errors="ignore")
            state = next((line.split()[1] for line in state_text.splitlines() if line.startswith("State:")), "")
            if state in {"Z", "X"}:
                continue
            if "main.py" in command and (cwd.startswith(managed_root) or cwd == str(PROJECT_LINK)):
                return True
        except (OSError, PermissionError, IndexError):
            continue
    return False


def copy_shared_configuration(legacy: Path) -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    for name in (".env", "settings.json", "demex.log", "telegram-control.log"):
        source = legacy / name
        target = SHARED / name
        if source.exists() and not target.exists():
            if source.is_file():
                shutil.copy2(source, target)
                if name == ".env":
                    target.chmod(0o600)


def link_shared_files(version_dir: Path) -> None:
    for name in (".env", "settings.json", "demex.log", "telegram-control.log"):
        shared_file = SHARED / name
        if shared_file.exists():
            target = version_dir / name
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(shared_file)


def install_dependencies(version_dir: Path) -> Path:
    python = shutil.which("python3") or shutil.which("python")
    if not python:
        raise RuntimeError("Python 3 não encontrado. Instale Python pelo Termux.")
    venv = version_dir / ".venv"
    subprocess.run([python, "-m", "venv", str(venv)], check=True, cwd=version_dir)
    vpy = venv / "bin" / "python"
    subprocess.run([str(vpy), "-m", "pip", "install", "--upgrade", "pip"], check=True, cwd=version_dir)
    subprocess.run([str(vpy), "-m", "pip", "install", "-r", str(version_dir / "requirements.txt")],
                   check=True, cwd=version_dir)
    return vpy


def validate_version(version_dir: Path, vpy: Path) -> None:
    for required in REQUIRED:
        if not (version_dir / required).is_file():
            raise RuntimeError(f"Arquivo essencial ausente no pacote: {required}")
    python_files = sorted(version_dir.rglob("*.py"))
    for source in python_files:
        if ".venv" in source.parts:
            continue
        subprocess.run([str(vpy), "-m", "py_compile", str(source)], check=True, cwd=version_dir)
    tests = version_dir / "tests"
    if tests.is_dir():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(version_dir)
        subprocess.run([str(vpy), "-m", "unittest", "discover", "-s", "tests", "-v"],
                       check=True, cwd=version_dir, env=env)


def atomic_current_switch(tag: str) -> str | None:
    previous = os.readlink(CURRENT) if CURRENT.is_symlink() else None
    temporary = MANAGER / "current.new"
    try:
        if temporary.is_symlink() or temporary.exists():
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            else:
                temporary.unlink()
        temporary.symlink_to(Path("versions") / tag)
        os.replace(temporary, CURRENT)
    except Exception:
        if temporary.is_symlink():
            temporary.unlink()
        raise
    return previous


def restore_current(previous: str | None) -> None:
    if previous is None:
        if CURRENT.is_symlink():
            CURRENT.unlink()
        return
    temporary = MANAGER / "current.rollback"
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.symlink_to(previous)
    os.replace(temporary, CURRENT)


def migrate_project_link() -> None:
    if PROJECT_LINK.is_symlink():
        return
    if not PROJECT_LINK.exists():
        PROJECT_LINK.symlink_to(CURRENT)
        return
    if not PROJECT_LINK.is_dir():
        raise RuntimeError(f"Caminho do projeto existe e não é diretório: {PROJECT_LINK}")
    copy_shared_configuration(PROJECT_LINK)
    backup_root = MANAGER / "legacy"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"checkout-{time.strftime('%Y%m%d-%H%M%S')}"
    os.replace(PROJECT_LINK, backup)
    try:
        PROJECT_LINK.symlink_to(CURRENT)
    except Exception:
        os.replace(backup, PROJECT_LINK)
        raise
    log(f"Projeto antigo preservado em {backup}; caminho original convertido em link para a versão ativa.")


def prune_versions(active_tag: str) -> None:
    candidates = sorted(
        (p for p in VERSIONS.iterdir() if p.is_dir() and not p.name.endswith(".staging")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    retained = 0
    for path in candidates:
        if path.name == active_tag or retained < KEEP_RELEASES - 1:
            retained += 1
            continue
        shutil.rmtree(path, ignore_errors=True)


def update() -> int:
    MANAGER.mkdir(parents=True, exist_ok=True)
    VERSIONS.mkdir(parents=True, exist_ok=True)
    SHARED.mkdir(parents=True, exist_ok=True)
    if robot_is_running():
        log("ATUALIZAÇÃO ADIADA: o DEMEX está em execução. Nenhum arquivo foi alterado.")
        return 2

    lock = MANAGER / "update.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        log("Outra atualização já está em andamento. Esta execução foi bloqueada.")
        return 2

    try:
        tag, assets = latest_release()
        final_dir = VERSIONS / tag
        if CURRENT.is_symlink() and CURRENT.resolve() == final_dir.resolve() and final_dir.exists():
            log(f"DEMEX já está atualizado na versão {tag}.")
            return 0
        if final_dir.exists():
            shutil.rmtree(final_dir)
        archive_data = request_bytes(assets["demex-source.tar.gz"], timeout=120)
        checksum_data = request_bytes(assets["SHA256SUMS"])
        expected = None
        for line in checksum_data.decode("utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == "demex-source.tar.gz":
                expected = parts[0].lower()
                break
        if not expected or sha256(archive_data) != expected:
            raise RuntimeError("SHA256 do pacote não confere. Instalação bloqueada.")

        free_bytes = shutil.disk_usage(MANAGER).free
        required_bytes = max(len(archive_data) * 2, 300 * 1024 * 1024)
        if free_bytes < required_bytes:
            raise RuntimeError(
                f"Espaço insuficiente: disponíveis {free_bytes // (1024 * 1024)} MB; "
                f"estimativa mínima {required_bytes // (1024 * 1024)} MB."
            )

        with tempfile.NamedTemporaryFile(prefix="demex-", suffix=".tar.gz", dir=MANAGER, delete=False) as stream:
            stream.write(archive_data)
            archive_path = Path(stream.name)
        try:
            final_dir.mkdir(parents=True)
            safe_extract(archive_path, final_dir)
        finally:
            archive_path.unlink(missing_ok=True)

        # O pacote é publicado com prefixo demex/; remove apenas esse nível.
        packaged_root = final_dir / "demex"
        if packaged_root.is_dir():
            for item in list(packaged_root.iterdir()):
                shutil.move(str(item), str(final_dir / item.name))
            packaged_root.rmdir()

        link_shared_files(final_dir)
        vpy = install_dependencies(final_dir)
        validate_version(final_dir, vpy)

        previous = atomic_current_switch(tag)
        try:
            for required in REQUIRED:
                if not (CURRENT / required).is_file():
                    raise RuntimeError(f"Verificação pós-ativação falhou: {required}")
            if not (CURRENT / ".venv/bin/python").is_file():
                raise RuntimeError("Ambiente virtual não encontrado após ativação.")
            migrate_project_link()
        except Exception:
            restore_current(previous)
            raise

        prune_versions(tag)
        log(f"ATUALIZAÇÃO CONCLUÍDA: versão {tag} instalada e validada. O robô permaneceu parado.")
        return 0
    except urllib.error.URLError as exc:
        log(f"FALHA DE CONEXÃO: {exc}. A versão ativa foi preservada.")
        return 1
    except subprocess.CalledProcessError as exc:
        log(f"VALIDAÇÃO/DEPENDÊNCIA REPROVADA (código {exc.returncode}). A versão ativa foi preservada.")
        return 1
    except (OSError, tarfile.TarError, ValueError, RuntimeError, KeyError) as exc:
        log(f"ATUALIZAÇÃO NÃO CONCLUÍDA: {exc}. A versão ativa foi preservada.")
        return 1
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def status() -> int:
    print("Atualizador DEMEX: disponível.")
    if CURRENT.is_symlink() and CURRENT.exists():
        print(f"Versão ativa: {CURRENT.resolve().name}")
        print(f"Projeto: {PROJECT_LINK}")
        vpy = CURRENT / ".venv/bin/python"
        if vpy.exists():
            print(subprocess.check_output([str(vpy), "--version"], text=True).strip())
    else:
        print("Versão ativa: ainda não instalada.")
    print(f"Robô DEMEX: {'EM EXECUÇÃO' if robot_is_running() else 'PARADO'}")
    print(f"Log: {LOG}")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "atualizar"
    if command in {"atualizar", "update", "instalar", "install"}:
        return update()
    if command in {"status"}:
        return status()
    print("Uso: demex-auto-update.sh {instalar|atualizar|status}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
