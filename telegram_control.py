"""Private Telegram command listener for safely controlling the DEMEX process.

Run this service separately from main.py. It only accepts commands from the
configured TELEGRAM_CHAT_ID and never sends or places broker orders itself.
"""
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import shutil

ROOT = Path(__file__).resolve().parent
STOP_FILE = ROOT / ".demex_stop"
PID_FILE = ROOT / ".demex-telegram-robot.pid"
SHELL_PID_FILE = ROOT / ".demex.pid"
LOCK_FILE = ROOT / ".demex-telegram-control.lock"
ROBOT_LOG = ROOT / ".demex-telegram-robot.log"
API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("demex.telegram_control")


def load_local_env():
    """Load only missing environment values; never print credentials."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_command(text):
    """Return a lowercase Telegram command without an optional @bot suffix."""
    if not isinstance(text, str):
        return None
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    if not first.startswith("/"):
        return None
    return first.split("@", 1)[0].lower()


def is_authorized_chat(message, allowed_chat_id):
    chat = message.get("chat") or {}
    return (
        str(chat.get("id", "")) == str(allowed_chat_id)
        and chat.get("type") == "private"
    )


def _pid_is_demex(pid):
    """Confirm a PID belongs to main.py running from this repository."""
    try:
        cwd = Path("/proc/{}/cwd".format(pid)).resolve()
        cmdline = Path("/proc/{}/cmdline".format(pid)).read_bytes()
    except (OSError, ProcessLookupError, PermissionError):
        return False
    if cwd != ROOT:
        return False
    args = [part.decode("utf-8", "ignore") for part in cmdline.split(b"\0") if part]
    return any(arg == "main.py" or arg.endswith("/main.py") for arg in args)


def find_robot_pid():
    """Find a live DEMEX process, including one started manually in Termux."""
    try:
        saved_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        saved_pid = None
    if saved_pid and _pid_is_demex(saved_pid):
        return saved_pid
    if saved_pid:
        PID_FILE.unlink(missing_ok=True)

    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid != os.getpid() and _pid_is_demex(pid):
            return pid
    return None


class TelegramControl:
    def __init__(self, token, chat_id):
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.offset = None
        self.robot_process = None
        self.stop_requested_pid = None

    def api_call(self, method, payload=None):
        if not self.token:
            raise RuntimeError("Token do Telegram não configurado.")
        if not shutil.which("curl"):
            raise RuntimeError("O comando curl não está disponível no Termux.")
        url = "{}/bot{}/{}".format(API_BASE, self.token, method)
        body = json.dumps(payload or {}, ensure_ascii=False)
        # Send credentials and URL through curl's stdin config, not process arguments.
        config = "\n".join((
            "url = {}".format(json.dumps(url)),
            'request = "POST"',
            'header = "Content-Type: application/json"',
            "data = {}".format(json.dumps(body)),
            "silent",
            "show-error",
            "max-time = {}".format(POLL_TIMEOUT + 10),
            "",
        ))
        try:
            response = subprocess.run(
                ["curl", "-4", "--http1.1", "--config", "-"],
                input=config,
                capture_output=True,
                text=True,
                timeout=POLL_TIMEOUT + 12,
                check=False,
            )
            if response.returncode != 0:
                raise RuntimeError("Falha de comunicação com o Telegram.")
            result = json.loads(response.stdout)
        except (subprocess.SubprocessError, OSError, ValueError):
            # Never log curl stderr or its config: they may contain the bot token.
            raise RuntimeError("Falha de comunicação com o Telegram.") from None
        if not result.get("ok"):
            # A descrição da API não contém o token e ajuda a distinguir
            # conflito de polling, credenciais inválidas e falhas temporárias.
            code = result.get("error_code")
            description = str(result.get("description") or "resposta inválida")
            raise RuntimeError(
                "Telegram API {}: {}".format(code or "erro", description[:240])
            )
        return result.get("result")

    def reply(self, chat_id, text):
        try:
            self.api_call("sendMessage", {"chat_id": chat_id, "text": text})
        except Exception as exc:
            log.warning("Não foi possível responder no Telegram: %s", exc)

    def start_robot(self, chat_id):
        existing_pid = find_robot_pid()
        if existing_pid:
            PID_FILE.write_text(str(existing_pid), encoding="utf-8")
            SHELL_PID_FILE.write_text(str(existing_pid), encoding="utf-8")
            self.reply(chat_id, "🟡 O DEMEX já está ligado (PID {}).".format(existing_pid))
            return

        STOP_FILE.unlink(missing_ok=True)
        log_handle = ROBOT_LOG.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "main.py")],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            log_handle.close()
            log.exception("Não foi possível iniciar o processo DEMEX.")
            self.reply(chat_id, "❌ Não consegui iniciar o DEMEX. Confira o log no Termux.")
            return
        log_handle.close()
        self.robot_process = process
        PID_FILE.write_text(str(process.pid), encoding="utf-8")
        SHELL_PID_FILE.write_text(str(process.pid), encoding="utf-8")

        # Aguarda a criação do processo visível em /proc. Isso evita confirmar
        # uma inicialização que falhou ou perdeu a disputa pela trava única.
        deadline = time.monotonic() + 3.0
        active_pid = None
        while time.monotonic() < deadline:
            active_pid = find_robot_pid()
            if active_pid:
                break
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if active_pid:
            if active_pid != process.pid:
                self.reply(
                    chat_id,
                    "🟡 O DEMEX já estava ligado (PID {}). Não iniciei outra instância.".format(active_pid)
                )
            else:
                self.reply(
                    chat_id,
                    "🚀 DEMEX iniciado no Termux (PID {}). "
                    "A execução só será liberada após confirmar PRACTICE/DEMO na corretora. "
                    "Acompanhe os registros em .demex-telegram-robot.log.".format(active_pid)
                )
            return

        PID_FILE.unlink(missing_ok=True)
        SHELL_PID_FILE.unlink(missing_ok=True)
        self.robot_process = None
        self.reply(
            chat_id,
            "❌ O processo DEMEX não permaneceu ativo após o comando. "
            "Confira .demex-telegram-robot.log no Termux."
        )

    def stop_robot(self, chat_id):
        pid = find_robot_pid()
        if not pid:
            self.reply(chat_id, "ℹ️ O DEMEX já está desligado.")
            return
        # main.py checks this flag between scans and after an active trade settles.
        STOP_FILE.touch(exist_ok=True)
        self.stop_requested_pid = pid
        self.reply(
            chat_id,
            "🛑 Pedido de parada recebido. Nenhuma nova entrada será iniciada. "
            "Se houver uma operação em andamento, o DEMEX aguardará o resultado "
            "antes de encerrar."
        )

    def status_robot(self, chat_id):
        pid = find_robot_pid()
        if pid:
            self.reply(chat_id, "🟢 DEMEX está LIGADO (PID {}).".format(pid))
        else:
            self.reply(chat_id, "⚫ DEMEX está DESLIGADO.")

    def handle_update(self, update):
        message = update.get("message") or update.get("edited_message") or {}
        if not is_authorized_chat(message, self.chat_id):
            return
        command = parse_command(message.get("text"))
        chat_id = message["chat"]["id"]
        if command == "/start":
            self.start_robot(chat_id)
        elif command == "/stop":
            self.stop_robot(chat_id)
        elif command == "/status":
            self.status_robot(chat_id)
        elif command in ("/help", "/ajuda"):
            self.reply(chat_id, "Comandos DEMEX:\n/start — ligar\n/stop — desligar com segurança\n/status — consultar estado")
        elif command:
            self.reply(chat_id, "Comando não reconhecido. Envie /help para ver os comandos.")

    def check_stopped_process(self):
        if self.stop_requested_pid is None:
            return
        if _pid_is_demex(self.stop_requested_pid):
            return
        PID_FILE.unlink(missing_ok=True)
        SHELL_PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)
        self.reply(self.chat_id, "✅ DEMEX desligado com segurança.")
        self.stop_requested_pid = None

    def discard_old_updates(self):
        # Prevent an old /start sent before the listener was launched from
        # unexpectedly starting the robot later.
        updates = self.api_call("getUpdates", {"offset": -1, "limit": 1, "timeout": 0})
        if updates:
            self.offset = int(updates[-1]["update_id"]) + 1

    def initialize_connection(self):
        """Validate the bot and prepare long polling before consuming commands."""
        self.api_call("getMe")
        # Long polling and a configured webhook cannot be used simultaneously.
        # Keep pending updates; discard_old_updates applies the existing safe
        # startup policy after webhook mode has been disabled.
        self.api_call("deleteWebhook", {"drop_pending_updates": False})
        self.discard_old_updates()

    def run(self):
        lock_handle = LOCK_FILE.open("w", encoding="utf-8")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_handle.close()
            raise RuntimeError("O serviço de controle do Telegram já está ativo.")
        log.info("Serviço de controle do Telegram iniciado.")
        initialized = False
        while True:
            self.check_stopped_process()
            try:
                # A inicialização também fica dentro do ciclo de reconexão.
                # Uma falha de rede no primeiro contato não mata o listener.
                if not initialized:
                    self.initialize_connection()
                    initialized = True
                    log.info("Conexão com o bot Telegram validada; aguardando comandos.")
                payload = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
                if self.offset is not None:
                    payload["offset"] = self.offset
                updates = self.api_call("getUpdates", payload) or []
                for update in updates:
                    self.offset = int(update["update_id"]) + 1
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log.warning("Listener do Telegram aguardando reconexão: %s", exc)
                time.sleep(5)


def main():
    load_local_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise SystemExit("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env.")
    try:
        TelegramControl(token, chat_id).run()
    except KeyboardInterrupt:
        log.info("Serviço de controle encerrado pelo usuário.")
    except RuntimeError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
