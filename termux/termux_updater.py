#!/usr/bin/env python3
"""Atualizador transacional do DEMEX para Android/Termux; nunca inicia o robô."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
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
CHECK_INTERVAL = 60
AGENT_PID_FILE = HOME / ".demex-auto-update.pid"
REQUIRED = ("main.py", "settings.json", "requirements.txt", "demex.sh", "telegram_control.py", "strategies/my_strategy.py")


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
        url, headers={"User-Agent": "DEMEX-Termux-Updater", "Accept": "application/vnd.github+json"}
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
        for item in payload.get("assets", []) if item.get("name") and item.get("browser_download_url")
    }
    if "demex-source.tar.gz" not in assets or "SHA256SUMS" not in assets:
        raise RuntimeError("A release não contém o pacote e o arquivo SHA256 obrigatórios.")
    return tag, assets


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def legacy_sync_is_running() -> bool:
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if "demex-agent.sh" in command and any(token in command for token in (" _run", " sync-once", " sincronizar")):
                return True
            if ".demex-auto-update.sh" in command and " loop" in command:
                return True
        except (OSError, PermissionError):
            continue
    return False


def robot_is_running() -> bool:
    managed_root = str(MANAGER.resolve())
    project_root = str(PROJECT_LINK.resolve()) if PROJECT_LINK.exists() else str(PROJECT_LINK)
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            cwd = str((proc / "cwd").resolve())
            state_text = (proc / "status").read_text(errors="ignore")
            state = next((line.split()[1] for line in state_text.splitlines() if line.startswith("State:")), "")
            if state in {"Z", "X"}:
                continue
            if "main.py" in command and (
                cwd == project_root or cwd.startswith(managed_root + os.sep)
                or cwd.startswith(project_root + os.sep)
            ):
                return True
        except (OSError, PermissionError, IndexError):
            continue
    return False



def find_telegram_listeners() -> list[dict[str, object]]:
    """Locate every live Telegram listener, including stale versioned installs."""
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            raw = (proc / "cmdline").read_bytes()
            args = [part.decode("utf-8", "ignore") for part in raw.split(b"\0") if part]
            script_arg = next((arg for arg in args if Path(arg).name == "telegram_control.py"), None)
            if script_arg is None:
                continue
            state_text = (proc / "status").read_text(errors="ignore")
            state = next((line.split()[1] for line in state_text.splitlines() if line.startswith("State:")), "")
            if state in {"Z", "X"}:
                continue
            cwd = (proc / "cwd").resolve()
            script_path = Path(script_arg)
            if not script_path.is_absolute():
                script_path = cwd / script_path
            found.append({
                "pid": int(proc.name),
                "cwd": str(cwd),
                "script": str(script_path.resolve()),
            })
        except (OSError, PermissionError, ValueError, IndexError):
            continue
    return found


def stop_telegram_listener(pid: int, timeout: float = 10.0) -> None:
    """Ask one listener to exit; never force-kill it or touch the robot."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise RuntimeError(f"Sem permissão para reiniciar o controle Telegram (PID {pid}).") from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = Path(f"/proc/{pid}")
        if not proc.exists():
            return
        try:
            status_text = (proc / "status").read_text(errors="ignore")
            state = next((line.split()[1] for line in status_text.splitlines() if line.startswith("State:")), "")
            if state in {"Z", "X"}:
                return
        except (OSError, PermissionError, IndexError):
            return
        time.sleep(0.2)
    raise RuntimeError(
        f"O controle Telegram (PID {pid}) não encerrou no prazo. "
        "Atualização cancelada; o robô não foi alterado."
    )


def start_telegram_listener(version_dir: Path) -> int:
    """Start the listener from the newly active version and verify it stays alive."""
    script = version_dir / "telegram_control.py"
    python = version_dir / ".venv" / "bin" / "python"
    if not script.is_file() or not python.is_file():
        raise RuntimeError("A versão não contém o controle Telegram ou seu Python virtual.")
    SHARED.mkdir(parents=True, exist_ok=True)
    log_path = SHARED / "telegram-control.log"
    with log_path.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [str(python), str(script)], cwd=version_dir,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if Path(f"/proc/{process.pid}").exists() and process.poll() is None:
            return process.pid
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError(
        "O controle Telegram não permaneceu ativo na nova versão. "
        "Confira ~/.demex/shared/telegram-control.log."
    )

def _pid_is_updater(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        return "termux_updater.py" in command
    except (OSError, PermissionError):
        return False


def acquire_lock(lock: Path) -> None:
    try:
        lock.mkdir()
    except FileExistsError:
        owner = lock / "owner"
        try:
            pid = int(owner.read_text(encoding="ascii").strip())
            stale = not _pid_is_updater(pid)
        except (OSError, ValueError):
            stale = time.time() - lock.stat().st_mtime > 120
        if not stale:
            raise RuntimeError("Outra atualização já está em andamento.")
        shutil.rmtree(lock, ignore_errors=False)
        lock.mkdir()
    (lock / "owner").write_text(str(os.getpid()), encoding="ascii")


def copy_shared_configuration(legacy: Path) -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    for name in (".env", "settings.json", "demex.log", "telegram-control.log"):
        source, target = legacy / name, SHARED / name
        if source.exists() and not target.exists() and source.is_file():
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
    for source in sorted(version_dir.rglob("*.py")):
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
    if temporary.is_symlink() or temporary.exists():
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        else:
            temporary.unlink()
    temporary.symlink_to(Path("versions") / tag)
    os.replace(temporary, CURRENT)
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
    legacy_root = MANAGER / "legacy"
    legacy_root.mkdir(parents=True, exist_ok=True)
    backup = legacy_root / f"checkout-{time.strftime('%Y%m%d-%H%M%S')}"
    os.replace(PROJECT_LINK, backup)
    try:
        PROJECT_LINK.symlink_to(CURRENT)
    except Exception:
        os.replace(backup, PROJECT_LINK)
        raise
    log(f"Checkout anterior preservado em {backup}; caminho do projeto convertido em link simbólico.")


def prune_versions(active_tag: str) -> None:
    candidates = sorted(
        (p for p in VERSIONS.iterdir() if p.is_dir() and not p.name.endswith(".staging")),
        key=lambda p: p.stat().st_mtime, reverse=True
    )
    retained = 0
    for path in candidates:
        if path.name == active_tag or retained < KEEP_RELEASES - 1:
            retained += 1
            continue
        shutil.rmtree(path, ignore_errors=True)


def update() -> int:
    # Evita manter o diretório de trabalho dentro do checkout que será movido
    # para legacy durante a migração inicial.
    os.chdir(HOME)
    MANAGER.mkdir(parents=True, exist_ok=True)
    VERSIONS.mkdir(parents=True, exist_ok=True)
    SHARED.mkdir(parents=True, exist_ok=True)
    if robot_is_running():
        log("ATUALIZAÇÃO ADIADA: DEMEX está em execução. Nenhum arquivo foi alterado.")
        return 2
    if legacy_sync_is_running():
        log("ATUALIZAÇÃO BLOQUEADA: agente antigo de sincronização ainda está ativo. Encerre-o antes da migração para evitar duas atualizações concorrentes.")
        return 2

    discovered_listeners = find_telegram_listeners()
    legacy_root = PROJECT_LINK.resolve() if PROJECT_LINK.exists() and not PROJECT_LINK.is_symlink() else None
    managed_listeners = []
    for listener in discovered_listeners:
        script_value = listener.get("script")
        if not script_value:
            continue
        try:
            script_path = Path(str(script_value)).resolve()
            script_path.relative_to(MANAGER.resolve())
            is_managed_version = True
        except (ValueError, OSError):
            is_managed_version = False
        is_legacy_listener = False
        if legacy_root is not None:
            try:
                script_path.relative_to(legacy_root)
                is_legacy_listener = True
            except (ValueError, OSError, UnboundLocalError):
                pass
        if is_managed_version or is_legacy_listener:
            managed_listeners.append(listener)

    if legacy_root is not None and any(
        item.get("script") and Path(str(item["script"])).resolve().is_relative_to(legacy_root)
        for item in managed_listeners
    ):
        log(
            "ATUALIZAÇÃO BLOQUEADA: o controle Telegram ainda está executando "
            "diretamente do checkout antigo. Encerre somente o listener Telegram "
            "antes da primeira migração; o robô não precisa ser desligado."
        )
        return 2

    listeners = managed_listeners

    lock = MANAGER / "update.lock"
    try:
        acquire_lock(lock)
    except (FileExistsError, RuntimeError, OSError) as exc:
        log(f"ATUALIZAÇÃO BLOQUEADA: {exc}")
        return 2

    stopped_listeners: list[int] = []
    previous_listener_version: Path | None = None
    listener_restarted = False
    try:
        tag, assets = latest_release()
        if not tag.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise RuntimeError("A tag da release contém caracteres não permitidos.")
        final_dir = VERSIONS / tag
        if CURRENT.is_symlink() and CURRENT.exists() and CURRENT.resolve() == final_dir.resolve():
            if all((CURRENT / item).is_file() for item in REQUIRED) and (CURRENT / ".venv/bin/python").is_file():
                log(f"DEMEX já está atualizado na versão {tag}.")
                return 0
            raise RuntimeError("A versão ativa está incompleta. Não será sobrescrita automaticamente; a versão anterior precisa ser recuperada.")

        archive_data = request_bytes(assets["demex-source.tar.gz"], timeout=180)
        checksum_data = request_bytes(assets["SHA256SUMS"])
        expected = next((
            line.split()[0].lower() for line in checksum_data.decode("utf-8").splitlines()
            if len(line.split()) >= 2 and line.split()[-1].lstrip("*") == "demex-source.tar.gz"
        ), None)
        if not expected or sha256(archive_data) != expected:
            raise RuntimeError("SHA256 do pacote não confere. Instalação bloqueada.")

        free_bytes = shutil.disk_usage(MANAGER).free
        required_bytes = max(len(archive_data) * 3, 500 * 1024 * 1024)
        if free_bytes < required_bytes:
            raise RuntimeError(
                f"Espaço insuficiente: disponíveis {free_bytes // (1024 * 1024)} MB; "
                f"estimativa mínima {required_bytes // (1024 * 1024)} MB."
            )

        if final_dir.exists():
            shutil.rmtree(final_dir)
        with tempfile.NamedTemporaryFile(prefix="demex-", suffix=".tar.gz", dir=MANAGER, delete=False) as stream:
            stream.write(archive_data)
            archive_path = Path(stream.name)
        try:
            final_dir.mkdir()
            safe_extract(archive_path, final_dir)
        finally:
            archive_path.unlink(missing_ok=True)

        packaged_root = final_dir / "demex"
        if packaged_root.is_dir():
            for item in list(packaged_root.iterdir()):
                shutil.move(str(item), str(final_dir / item.name))
            packaged_root.rmdir()

        # Copia configurações locais antes de criar os links compartilhados na versão nova.
        if PROJECT_LINK.exists() and not PROJECT_LINK.is_symlink():
            copy_shared_configuration(PROJECT_LINK)
        link_shared_files(final_dir)
        vpy = install_dependencies(final_dir)
        validate_version(final_dir, vpy)

        # A listener usa caminhos absolutos da versão em que foi iniciado.
        # Reinicie apenas esse serviço (nunca o robô) para não deixar /start
        # apontando para uma instalação antiga.
        if CURRENT.is_symlink() and CURRENT.exists():
            previous_listener_version = CURRENT.resolve()
        for listener in listeners:
            pid = int(listener["pid"])
            stop_telegram_listener(pid)
            stopped_listeners.append(pid)

        previous = atomic_current_switch(tag)
        try:
            for required in REQUIRED:
                if not (CURRENT / required).is_file():
                    raise RuntimeError(f"Verificação pós-ativação falhou: {required}")
            if not (CURRENT / ".venv/bin/python").is_file():
                raise RuntimeError("Ambiente virtual não encontrado após ativação.")
            migrate_project_link()
            if stopped_listeners:
                new_pid = start_telegram_listener(final_dir)
                listener_restarted = True
                log(f"Controle Telegram reiniciado na versão {tag} (PID {new_pid}).")
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
    except Exception as exc:
        log(f"ERRO INESPERADO DURANTE A ATUALIZAÇÃO: {type(exc).__name__}: {exc}. A versão ativa foi preservada.")
        return 1
    finally:
        if stopped_listeners and not listener_restarted and previous_listener_version is not None:
            try:
                restored_pid = start_telegram_listener(previous_listener_version)
                log(f"Controle Telegram restaurado na versão anterior (PID {restored_pid}).")
            except Exception as restart_error:
                log(
                    "ATENÇÃO: não foi possível restaurar automaticamente o controle Telegram: "
                    f"{type(restart_error).__name__}. O robô não foi alterado; "
                    "consulte o log e reinicie somente o listener quando possível."
                )
        try:
            (lock / "owner").unlink(missing_ok=True)
            lock.rmdir()
        except OSError:
            pass


def agent_running() -> bool:
    try:
        pid = int(AGENT_PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    return _pid_is_updater(pid)


def start_agent() -> int:
    if agent_running():
        log(f"Atualizador automático já está ativo (PID {AGENT_PID_FILE.read_text().strip()}).")
        return 0
    bootstrapper = HOME / ".demex-bootstrap.sh"
    if not bootstrapper.is_file():
        log("Bootstrapper não encontrado. Execute primeiro o inicializador do DEMEX.")
        return 1
    try:
        with LOG.open("a", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "loop"],
                cwd=HOME, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        AGENT_PID_FILE.write_text(str(process.pid), encoding="ascii")
        time.sleep(0.3)
        if not _pid_is_updater(process.pid):
            AGENT_PID_FILE.unlink(missing_ok=True)
            log("Não foi possível manter o atualizador automático em execução.")
            return 1
        log(f"Atualizador automático iniciado (PID {process.pid}); consulta a cada {CHECK_INTERVAL} segundos.")
        return 0
    except OSError as exc:
        log(f"Falha ao iniciar o atualizador automático: {exc}")
        return 1


def stop_agent() -> int:
    try:
        pid = int(AGENT_PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        AGENT_PID_FILE.unlink(missing_ok=True)
        log("Atualizador automático já estava parado.")
        return 0
    if _pid_is_updater(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            log(f"Pedido de parada enviado ao atualizador automático (PID {pid}).")
        except OSError as exc:
            log(f"Não foi possível parar o atualizador automático: {exc}")
            return 1
    AGENT_PID_FILE.unlink(missing_ok=True)
    return 0


def run_loop() -> int:
    signal.signal(signal.SIGTERM, lambda *_: raise_system_exit())
    bootstrapper = HOME / ".demex-bootstrap.sh"
    log(f"Agente automático iniciado; verificações a cada {CHECK_INTERVAL} segundos.")
    while True:
        if not bootstrapper.is_file():
            log("Bootstrapper ausente; nova tentativa no próximo ciclo.")
        else:
            try:
                with LOG.open("a", encoding="utf-8") as output:
                    subprocess.run(["bash", str(bootstrapper), "atualizar"], cwd=HOME,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   check=False)
            except OSError as exc:
                log(f"Falha na verificação automática: {exc}")
        time.sleep(CHECK_INTERVAL)


def raise_system_exit() -> None:
    raise SystemExit(0)


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
    print(f"Atualizador automático: {'ATIVO' if agent_running() else 'PARADO'}")
    print(f"Robô DEMEX: {'EM EXECUÇÃO' if robot_is_running() else 'PARADO'}")
    print(f"Log: {LOG}")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "atualizar"
    if command in {"atualizar", "update", "instalar", "install"}:
        return update()
    if command == "iniciar":
        return start_agent()
    if command == "parar":
        return stop_agent()
    if command == "loop":
        return run_loop()
    if command == "status":
        return status()
    print("Uso: demex-auto-update.sh {instalar|atualizar|iniciar|parar|status}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
