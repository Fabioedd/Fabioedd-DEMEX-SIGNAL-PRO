#!/data/data/com.termux/files/usr/bin/bash
# Gerencia o listener remoto do DEMEX pelo Telegram.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$(command -v python || true)"
PID_FILE="$ROOT/.demex-telegram-control.pid"
LOG_FILE="$ROOT/telegram-control.log"

if [ -z "$PYTHON" ]; then
  echo "Python não encontrado. Instale as dependências do DEMEX primeiro."
  exit 1
fi

find_listener_pid() {
  local proc pid proc_cwd cmdline
  for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue
    pid="${proc##*/}"
    [ "$pid" = "$$" ] && continue
    proc_cwd="$(readlink -f "$proc/cwd" 2>/dev/null || true)"
    [ "$proc_cwd" = "$ROOT" ] || continue
    cmdline="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
    case "$cmdline" in
      *telegram_control.py*) echo "$pid"; return 0 ;;
    esac
  done
  return 1
}

environment_ready() {
  "$PYTHON" -c 'from dotenv import load_dotenv; import os; load_dotenv(); raise SystemExit(0 if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip() else 1)' >/dev/null 2>&1
}

case "${1:-}" in
  iniciar|start)
    if ! environment_ready; then
      echo "Telegram não configurado. Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env local."
      exit 2
    fi
    if pid="$(find_listener_pid)"; then
      echo "$pid" > "$PID_FILE"
      echo "Controle do Telegram já está ativo (PID $pid)."
      exit 0
    fi
    rm -f "$PID_FILE"
    nohup "$PYTHON" "$ROOT/telegram_control.py" >> "$LOG_FILE" 2>&1 </dev/null &
    launch_pid=$!
    echo "$launch_pid" > "$PID_FILE"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if pid="$(find_listener_pid)"; then
        echo "$pid" > "$PID_FILE"
        echo "Controle do Telegram iniciado. Comandos: /start, /stop, /status e /help."
        echo "Log: $LOG_FILE"
        exit 0
      fi
      if ! kill -0 "$launch_pid" 2>/dev/null; then
        break
      fi
      sleep 0.3
    done
    rm -f "$PID_FILE"
    echo "O controle do Telegram não permaneceu ativo. Confira: tail -n 30 $LOG_FILE"
    exit 1
    ;;
  parar|stop)
    if pid="$(find_listener_pid)"; then
      kill "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Controle do Telegram parado. O DEMEX não foi desligado."
    else
      rm -f "$PID_FILE"
      echo "Controle do Telegram já estava parado."
    fi
    ;;
  status)
    if pid="$(find_listener_pid)"; then
      echo "Controle do Telegram: ATIVO (PID $pid)."
    else
      echo "Controle do Telegram: PARADO."
    fi
    ;;
  *)
    echo "Uso: bash telegram-control.sh {iniciar|parar|status}"
    exit 2
    ;;
esac
