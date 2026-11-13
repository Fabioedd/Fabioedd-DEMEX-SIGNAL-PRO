#!/data/data/com.termux/files/usr/bin/bash
# Compatibilidade para o antigo caminho ~/.demex-auto-update.sh.
# Instala o bootstrapper independente e delega toda atualização a ele.
set -Eeuo pipefail
HOME_DIR="${HOME:?HOME não definido}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BOOTSTRAP="$HOME_DIR/.demex-bootstrap.sh"
MANAGER="$HOME_DIR/.demex"
mkdir -p "$MANAGER"

if [ -f "$PROJECT_DIR/termux/demex-bootstrap.sh" ]; then
  install -m 700 "$PROJECT_DIR/termux/demex-bootstrap.sh" "$BOOTSTRAP"
fi
if [ -f "$PROJECT_DIR/termux/termux_updater.py" ]; then
  install -m 600 "$PROJECT_DIR/termux/termux_updater.py" "$MANAGER/termux_updater.py"
fi

if [ ! -x "$BOOTSTRAP" ]; then
  echo "Bootstrapper DEMEX não encontrado. Nada foi alterado."
  exit 1
fi
exec bash "$BOOTSTRAP" "${1:-atualizar}"
