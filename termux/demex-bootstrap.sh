#!/data/data/com.termux/files/usr/bin/bash
# Inicializador permanente do DEMEX. Não inicia o robô.
set -Eeuo pipefail
HOME_DIR="${HOME:?HOME não definido}"
MANAGER="$HOME_DIR/.demex"
UPDATER="$MANAGER/termux_updater.py"
PROJECT="$HOME_DIR/Fabioedd-DEMEX-SIGNAL-PRO"
LOG="$HOME_DIR/DEMEX_AUTO_UPDATE.log"

mkdir -p "$MANAGER"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

if ! command -v python3 >/dev/null 2>&1; then
  log "ERRO: Python 3 não encontrado. Instale-o pelo Termux: pkg install python."
  exit 1
fi

# Na migração inicial, usa o atualizador validado que acompanha o checkout local.
if [ ! -s "$UPDATER" ] && [ -f "$PROJECT/termux/termux_updater.py" ]; then
  install -m 600 "$PROJECT/termux/termux_updater.py" "$UPDATER"
fi

if [ ! -s "$UPDATER" ]; then
  log "ERRO: atualizador principal ausente. Execute novamente a instalação pelo atualizador do repositório."
  exit 1
fi

if ! python3 -m py_compile "$UPDATER" >/dev/null 2>&1; then
  log "ERRO: arquivo do atualizador principal está corrompido. A recuperação será feita na próxima versão do bootstrapper."
  exit 1
fi

exec python3 "$UPDATER" "${1:-atualizar}"
