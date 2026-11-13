#!/data/data/com.termux/files/usr/bin/bash
# Bootstrapper independente: recupera o atualizador principal a partir de uma Release validada.
set -Eeuo pipefail
HOME_DIR="${HOME:?HOME não definido}"
MANAGER="$HOME_DIR/.demex"
UPDATER="$MANAGER/termux_updater.py"
LOG="$HOME_DIR/DEMEX_AUTO_UPDATE.log"
mkdir -p "$MANAGER"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

command -v python3 >/dev/null 2>&1 || {
  log "ERRO: Python 3 não encontrado. Instale com: pkg install python"
  exit 1
}

recover_updater() {
  log "Conferindo e atualizando o atualizador principal pela última Release estável..."
  python3 - "$UPDATER" "$MANAGER/updater-release" <<'PY'
import hashlib, json, os, sys, tarfile, tempfile, urllib.request
from pathlib import Path

repo = "Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO"
api = f"https://api.github.com/repos/{repo}/releases/latest"
headers = {"User-Agent": "DEMEX-Termux-Bootstrap", "Accept": "application/vnd.github+json"}
def get(url):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()
release = json.loads(get(api).decode())
tag = str(release.get("tag_name", "")).strip()
if release.get("draft") or release.get("prerelease") or not tag:
    raise SystemExit("GitHub não retornou uma Release estável.")
destination = Path(sys.argv[1])
version_file = Path(sys.argv[2])
if destination.is_file() and version_file.is_file() and version_file.read_text().strip() == tag:
    print(f"Atualizador principal já está na versão {tag}.")
    raise SystemExit(0)
assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
if "demex-source.tar.gz" not in assets or "SHA256SUMS" not in assets:
    raise SystemExit("Release sem pacote ou SHA256.")
archive = get(assets["demex-source.tar.gz"])
sums = get(assets["SHA256SUMS"]).decode()
expected = next((line.split()[0].lower() for line in sums.splitlines()
                 if len(line.split()) >= 2 and line.split()[-1].lstrip("*") == "demex-source.tar.gz"), None)
if not expected or hashlib.sha256(archive).hexdigest() != expected:
    raise SystemExit("SHA256 inválido; arquivo recusado.")
with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
    tmp.write(archive)
    tmp.flush()
    with tarfile.open(tmp.name, "r:gz") as bundle:
        member = bundle.getmember("demex/termux/termux_updater.py")
        if not member.isfile():
            raise SystemExit("O arquivo do atualizador não é um arquivo regular.")
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit("Não foi possível ler o atualizador do pacote.")
        content = source.read()
destination.parent.mkdir(parents=True, exist_ok=True)
temporary = destination.with_suffix(".py.new")
temporary.write_bytes(content)
os.chmod(temporary, 0o600)
os.replace(temporary, destination)
version_tmp = version_file.with_suffix(".new")
version_tmp.write_text(tag + "\n")
os.replace(version_tmp, version_file)
print(f"Atualizador recuperado/atualizado para a Release {tag}.")
PY
}

COMMAND="${1:-atualizar}"
if [ "$COMMAND" != "status" ] || [ ! -s "$UPDATER" ] || ! python3 -m py_compile "$UPDATER" >/dev/null 2>&1; then
  recover_updater || {
    log "ERRO: não foi possível recuperar/atualizar o atualizador. A versão ativa não foi alterada."
    exit 1
  }
fi

exec python3 "$UPDATER" "$COMMAND"
