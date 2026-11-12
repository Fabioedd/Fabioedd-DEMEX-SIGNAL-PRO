#!/data/data/com.termux/files/usr/bin/bash
# DEMEX Agent: sincronizacao segura GitHub <-> Termux.
# Nao inicia, para ou reinicia o robô DEMEX.
set -Eeuo pipefail

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
ROOT="${DEMEX_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
cd "$ROOT"
REMOTE="${DEMEX_GIT_REMOTE:-origin}"
MAIN_BRANCH="${DEMEX_MAIN_BRANCH:-main}"
POLL_SECONDS="${DEMEX_POLL_SECONDS:-60}"
PID_FILE=".demex-agent.pid"
LOG_FILE=".demex-agent.log"
BACKUP_DIR=".demex-agent-backups"
LOCK_DIR=".demex-agent.lock"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
py() {
  if [ -x ".venv/bin/python" ]; then .venv/bin/python "$@"; else python "$@"; fi
}
is_allowed_path() {
  case "$1" in
    main.py|settings.json|signal_engine.py|backtest_filter.py|trade_manager.py|bullex_connector.py|strategies/*.py|tests/*.py)
      return 0 ;;
    *) return 1 ;;
  esac
}
require_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    log "ERRO: esta pasta nao e um repositorio Git."
    return 1
  }
  git remote get-url "$REMOTE" >/dev/null 2>&1 || {
    log "ERRO: remoto '$REMOTE' nao configurado."
    return 1
  }
}
robot_is_running() {
  # O robo mantém o PID no arquivo do lock enquanto segura o flock.
  # Confirmamos também cmdline, diretório de trabalho e estado do processo
  # para evitar confundir PID antigo ou outro projeto Python com o DEMEX.
  local pid proc cmdline proc_cwd proc_state repo_real
  repo_real="$(cd "$ROOT" && pwd -P)" || return 1

  if [ -r "$ROOT/.demex-robot.lock" ]; then
    pid="$(tr -cd '0-9' < "$ROOT/.demex-robot.lock" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && [ -r "/proc/$pid/cmdline" ]; then
      cmdline="$(tr '\\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
      proc_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
      proc_state="$(awk '/^State:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
      case "$proc_state" in Z|X) ;; *)
        case "$cmdline" in *main.py*) [ "$proc_cwd" = "$repo_real" ] && return 0 ;; esac
      esac
    fi
  fi

  # Fallback para sessões iniciadas por versões antigas sem arquivo de lock.
  for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue
    pid="${proc##*/}"
    proc_cwd="$(readlink -f "$proc/cwd" 2>/dev/null || true)"
    [ "$proc_cwd" = "$repo_real" ] || continue
    proc_state="$(awk '/^State:/ {print $2}' "$proc/status" 2>/dev/null || true)"
    case "$proc_state" in Z|X) continue ;; esac
    cmdline="$(tr '\\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
    case "$cmdline" in *main.py*) return 0 ;; esac
  done
  return 1
}

working_tree_clean() {
  git diff --quiet && git diff --cached --quiet || return 1
  local path
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
      .env|.venv/*|__pycache__/*|vendor/*|*.log|*.pid|.demex_stop|*.backup*|*.bak*|"-la .envpython main.py .demex_stop demex_teste.pid"|".envpython main.py") ;;
      *) log "Arquivo local nao rastreado bloqueia atualizacao: $path"; return 1 ;;
    esac
  done < <(git ls-files --others --exclude-standard)
  return 0
}

backup_incoming_changes() {
  local changed=()
  while IFS= read -r path; do
    [ -n "$path" ] && changed+=("$path")
  done < <(git diff --name-only HEAD "refs/remotes/$REMOTE/$MAIN_BRANCH")
  [ "${#changed[@]}" -gt 0 ] || return 0
  mkdir -p "$BACKUP_DIR"
  local stamp
  stamp="$(date '+%Y%m%d_%H%M%S')"
  local existing=()
  for path in "${changed[@]}"; do
    [ -e "$path" ] && existing+=("$path")
  done
  if [ "${#existing[@]}" -gt 0 ]; then
    tar -czf "$BACKUP_DIR/pre_update_$stamp.tar.gz" "${existing[@]}"
    log "Backup criado: $BACKUP_DIR/pre_update_$stamp.tar.gz"
  fi
}

publish_local_changes() {
  local changed=()
  while IFS= read -r path; do
    [ -n "$path" ] && changed+=("$path")
  done < <(git diff --name-only)
  while IFS= read -r path; do
    [ -n "$path" ] && changed+=("$path")
  done < <(git diff --cached --name-only)
  [ "${#changed[@]}" -gt 0 ] || return 0

  local unique=()
  local seen='|'
  for path in "${changed[@]}"; do
    if [[ "$seen" == *"|$path|"* ]]; then continue; fi
    seen="$seen$path|"
    is_allowed_path "$path" || {
      log "ALTERACAO LOCAL NAO PUBLICADA: arquivo fora da lista segura: $path"
      return 1
    }
    unique+=("$path")
  done

  if ! git config user.name >/dev/null; then git config user.name "DEMEX Agent"; fi
  if ! git config user.email >/dev/null; then git config user.email "demex-agent@users.noreply.github.com"; fi

  git add -- "${unique[@]}"
  if git diff --cached --quiet; then return 0; fi

  local sync_branch host
  host="$(hostname 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | cut -c1-24)"
  [ -n "$host" ] || host="termux"
  sync_branch="termux-sync-$host"

  git commit -m "DEMEX Termux: sincronizacao local $(date '+%Y-%m-%d %H:%M:%S')"
  log "Alteracoes locais commitadas; enviando para branch $sync_branch (nao para main)."
  git push "$REMOTE" "HEAD:refs/heads/$sync_branch" || {
    log "PUSH NAO CONCLUIDO. Verifique autenticacao/permissao Git do Termux."
    return 1
  }
  log "Alteracoes locais enviadas para GitHub/$sync_branch. Revise e integre por Pull Request."
}

push_pending_agent_commits() {
  local remote_ref="$1"
  local subject sync_branch host
  local found=0
  while IFS= read -r subject; do
    [ -n "$subject" ] || continue
    found=1
    case "$subject" in
      "DEMEX Termux: sincronizacao local "*) ;;
      *) return 1 ;;
    esac
  done < <(git log --format=%s "$remote_ref..HEAD")
  [ "$found" -eq 1 ] || return 1
  host="$(hostname 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | cut -c1-24)"
  [ -n "$host" ] || host="termux"
  sync_branch="termux-sync-$host"
  log "Tentando reenviar commits locais pendentes para $sync_branch."
  git push "$REMOTE" "HEAD:refs/heads/$sync_branch"
}
refresh_agent_copy() {
  if [ -f "$ROOT/demex-agent.sh" ] && [ "$SCRIPT_PATH" != "$ROOT/demex-agent.sh" ]; then
    cp "$ROOT/demex-agent.sh" "$ROOT/.demex-agent.sh.new"
    chmod 700 "$ROOT/.demex-agent.sh.new"
    mv "$ROOT/.demex-agent.sh.new" "$ROOT/.demex-agent.sh"
    log "Copia local do agente atualizada; a nova versao sera usada no proximo reinicio do agente."
  fi
}

test_remote_candidate() {
  local tmp
  tmp="$(mktemp -d "$ROOT/.demex-agent-test.XXXXXX")"
  trap 'rm -rf "$tmp"' RETURN
  git archive "refs/remotes/$REMOTE/$MAIN_BRANCH" | tar -x -C "$tmp"
  py -m compileall -q "$tmp"
  if [ -d "$tmp/tests" ]; then
    (cd "$tmp" && PYTHONPATH="$tmp" py -m unittest discover -s tests -v)
  fi
  rm -rf "$tmp"
  trap - RETURN
}

sync_once() {
  require_repo || return 1
  local branch
  branch="$(git branch --show-current)"
  if [ "$branch" != "$MAIN_BRANCH" ]; then
    log "Sincronizacao suspensa: branch local '$branch'; esperado '$MAIN_BRANCH'."
    return 1
  fi

  if ! working_tree_clean; then
    log "Alteracoes locais detectadas. Tentando publica-las em branch separada."
    publish_local_changes || return 1
  fi

  if ! working_tree_clean; then
    log "Atualizacao remota bloqueada: arvore de trabalho ainda possui alteracoes."
    return 1
  fi

  git fetch "$REMOTE" "$MAIN_BRANCH"
  local local_sha remote_sha
  local_sha="$(git rev-parse HEAD)"
  remote_sha="$(git rev-parse "refs/remotes/$REMOTE/$MAIN_BRANCH")"
  [ "$local_sha" = "$remote_sha" ] && {
    log "Termux ja esta atualizado ($local_sha)."
    return 0
  }

  if ! git merge-base --is-ancestor HEAD "refs/remotes/$REMOTE/$MAIN_BRANCH"; then
    if working_tree_clean && push_pending_agent_commits "refs/remotes/$REMOTE/$MAIN_BRANCH"; then
      log "Commits locais publicados na branch de sincronizacao; aguardando revisao/PR."
      return 0
    fi
    log "Atualizacao pausada: GitHub e Termux divergiram. Nenhum arquivo foi sobrescrito."
    return 1
  fi

  log "Nova versao encontrada no GitHub: $remote_sha. Validando antes de instalar."
  test_remote_candidate || {
    log "VALIDACAO FALHOU. Versao remota nao instalada."
    return 1
  }

  # Nunca troca arquivos do projeto enquanto o processo DEMEX está ativo.
  # Reconfere imediatamente antes da instalação para reduzir a janela de corrida.
  if robot_is_running; then
    log "ATUALIZACAO ADIADA: DEMEX esta em execucao; nenhum arquivo foi alterado."
    return 0
  fi

  backup_incoming_changes
  if robot_is_running; then
    log "ATUALIZACAO ADIADA: DEMEX iniciou durante a preparacao; backup preservado e instalacao cancelada."
    return 0
  fi
  git merge --ff-only "refs/remotes/$REMOTE/$MAIN_BRANCH"
  refresh_agent_copy
  log "Atualizacao instalada localmente. O processo do robô nao foi reiniciado."
}

run_loop() {
  log "DEMEX Agent iniciado. Consulta ao GitHub a cada $POLL_SECONDS segundos."
  while true; do
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      sync_once || true
      rmdir "$LOCK_DIR" 2>/dev/null || true
    else
      log "Outra sincronizacao esta em andamento; aguardando."
    fi
    sleep "$POLL_SECONDS"
  done
}

case "${1:-}" in
  instalar|install)
    require_repo
    [ "$(git branch --show-current)" = "$MAIN_BRANCH" ] || {
      log "Entre na branch $MAIN_BRANCH antes de instalar."
      exit 1
    }
    log "Agente preparado. Para iniciar: bash demex-agent.sh iniciar"
    ;;
  sincronizar|sync-once) sync_once ;;
  iniciar|start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      log "Agente ja esta em execucao (PID $(cat "$PID_FILE"))."
      exit 0
    fi
    rm -f "$PID_FILE"
    nohup bash "$SCRIPT_PATH" _run >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      log "Agente iniciado em segundo plano. Log: $LOG_FILE"
    else
      rm -f "$PID_FILE"
      log "Falha ao iniciar. Consulte $LOG_FILE."
      exit 1
    fi
    ;;
  parar|stop)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      kill "$(cat "$PID_FILE")"
      rm -f "$PID_FILE"
      log "Agente parado. O robô DEMEX nao foi afetado."
    else
      rm -f "$PID_FILE"
      log "Agente ja estava parado."
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      log "Agente ativo (PID $(cat "$PID_FILE"))."
    else
      log "Agente parado."
    fi
    ;;
  _run) run_loop ;;
  *)
    echo "Uso: bash demex-agent.sh {instalar|sincronizar|iniciar|parar|status}"
    exit 2
    ;;
esac
