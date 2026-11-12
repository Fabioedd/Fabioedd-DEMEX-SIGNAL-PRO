#!/data/data/com.termux/files/usr/bin/bash
# Controle simples do DEMEX no Termux.
set -u
cd "$(dirname "$0")" || exit 1

PID_FILE=".demex.pid"
STOP_FILE=".demex_stop"
LOG_FILE="demex.log"
PYTHON=".venv/bin/python"

case "${1:-}" in
  iniciar)
    if [ ! -x "$PYTHON" ]; then
      echo "Ambiente .venv não encontrado. Crie/instale o ambiente antes de iniciar."
      exit 1
    fi
    # Inicia também o listener remoto; sem token/chat ID o DEMEX continua funcionando normalmente.
    if [ -f "telegram-control.sh" ]; then
      bash telegram-control.sh iniciar || echo "Aviso: controle Telegram não iniciado. Confira TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env."
    fi
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "DEMEX já está em execução. Use: ./demex.sh status"
      exit 0
    fi
    rm -f "$STOP_FILE" "$PID_FILE"
    nohup "$PYTHON" main.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "DEMEX iniciado usando .venv. Log: $LOG_FILE"
    else
      rm -f "$PID_FILE"
      echo "O DEMEX não iniciou. Confira: tail -n 40 $LOG_FILE"
      exit 1
    fi
    ;;
  parar)
    if [ ! -f "$PID_FILE" ] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "DEMEX não está em execução."
      exit 0
    fi
    touch "$STOP_FILE"
    echo "Pedido de parada enviado. O robô não abrirá novas operações."
    echo "Aguardando a operação atual terminar e o resultado ser recebido..."
    while kill -0 "$(cat "$PID_FILE")" 2>/dev/null; do sleep 1; done
    rm -f "$PID_FILE"
    echo "DEMEX encerrado com segurança."
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "DEMEX está em execução."
    else
      rm -f "$PID_FILE"
      echo "DEMEX está parado."
    fi
    ;;
  sair)
    "$0" parar
    echo "Robô parado. Para fechar esta sessão do Termux, digite: exit"
    ;;
  *)
    echo "Uso: ./demex.sh {iniciar|parar|status|sair}"
    exit 2
    ;;
esac
