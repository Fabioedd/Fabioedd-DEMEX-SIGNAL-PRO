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
import hashlib, os, sys, tarfile, tempfile, urllib.parse, urllib.request
from pathlib import Path

repo = "Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO"
latest_page = f"https://github.com/{repo}/releases/latest"
headers = {"User-Agent": "DEMEX-Termux-Bootstrap", "Accept": "text/html"}

def get(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DEMEX-Termux-Bootstrap", "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

request = urllib.request.Request(latest_page, headers=headers)
with urllib.request.urlopen(request, timeout=60) as response:
    final_url = response.geturl()

parsed = urllib.parse.urlparse(final_url)
expected_prefix = f"/{repo}/releases/tag/"
if parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
    raise SystemExit("O GitHub não redirecionou para uma Release estável válida.")
if not parsed.path.startswith(expected_prefix):
    raise SystemExit("O GitHub não redirecionou para uma Release estável válida.")
tag = urllib.parse.unquote(parsed.path[len(expected_prefix):]).strip("/")
if not tag or "/" in tag or not tag.replace(".", "").replace("-", "").replace("_", "").isalnum():
    raise SystemExit("A tag da Release contém caracteres não permitidos.")

destination = Path(sys.argv[1])
version_file = Path(sys.argv[2])
if destination.is_file() and version_file.is_file() and version_file.read_text().strip() == tag:
    print(f"Atualizador principal já está na versão {tag}.")
    raise SystemExit(0)

base = f"https://github.com/{repo}/releases/download/{urllib.parse.quote(tag, safe='')}"
archive = get(f"{base}/demex-source.tar.gz")
sums = get(f"{base}/SHA256SUMS").decode()
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
version_tmp.write_text(tag + "\\n")
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
