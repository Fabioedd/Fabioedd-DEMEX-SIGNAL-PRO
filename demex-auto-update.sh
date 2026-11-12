#!/data/data/com.termux/files/usr/bin/bash
# DEMEX automatic GitHub updater for Termux.
# Updates only the local source tree. It NEVER starts, stops, or restarts main.py.

set -u

REPO_URL="https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO.git"
REPO_DIR="${HOME}/Fabioedd-DEMEX-SIGNAL-PRO"
SCRIPT_PATH="${HOME}/.demex-auto-update.sh"
PID_FILE="${HOME}/.demex-auto-update.pid"
LOG_FILE="${HOME}/DEMEX_AUTO_UPDATE.log"
BRANCH="main"
CHECK_INTERVAL=60

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

robot_is_running() {
    # Detecta somente o main.py deste repositorio; evita falsos positivos
    # causados por outros projetos Python em execucao no mesmo Android.
    local pid proc_cwd proc_state cmdline repo_real
    repo_real="$(cd "$REPO_DIR" 2>/dev/null && pwd -P)" || return 1

    while IFS= read -r pid; do
        [ -r "/proc/$pid/cmdline" ] || continue
        proc_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
        [ "$proc_cwd" = "$repo_real" ] || continue

        proc_state="$(awk '/^State:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
        case "$proc_state" in
            Z|X) continue ;;
        esac

        cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        case "$cmdline" in
            *main.py*) return 0 ;;
        esac
    done < <(pgrep -f '[p]ython.*main.py' 2>/dev/null || true)

    return 1
}

tracked_tree_is_clean() {
    git -C "$REPO_DIR" diff --quiet &&
    git -C "$REPO_DIR" diff --cached --quiet
}

update_once() {
    if [ ! -d "$REPO_DIR/.git" ]; then
        log "ERRO: pasta do projeto ou repositório Git não encontrado."
        return 1
    fi

    current_branch="$(git -C "$REPO_DIR" branch --show-current 2>/dev/null || true)"
    if [ "$current_branch" != "$BRANCH" ]; then
        log "ATUALIZAÇÃO ADIADA: branch local é '$current_branch', esperado '$BRANCH'."
        return 1
    fi

    if ! tracked_tree_is_clean; then
        log "ATUALIZAÇÃO ADIADA: existem alterações locais em arquivos rastreados; nada será sobrescrito."
        return 1
    fi

    if ! git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"; then
        log "ERRO: não foi possível consultar o GitHub; nova tentativa no próximo ciclo."
        return 1
    fi

    old_sha="$(git -C "$REPO_DIR" rev-parse HEAD)" || return 1
    remote_sha="$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")" || return 1

    if [ "$old_sha" = "$remote_sha" ]; then
        return 0
    fi

    if ! git -C "$REPO_DIR" merge-base --is-ancestor "$old_sha" "$remote_sha"; then
        log "ATUALIZAÇÃO BLOQUEADA: histórico local e GitHub divergiram; nenhuma redefinição será feita."
        return 1
    fi

    if robot_is_running; then
        log "ATUALIZAÇÃO AGUARDANDO: DEMEX está em execução. Os arquivos não serão alterados durante a sessão."
        return 0
    fi

    if ! git -C "$REPO_DIR" merge --ff-only "$remote_sha"; then
        log "ERRO: atualização fast-forward não foi concluída; arquivos locais preservados."
        return 1
    fi

    new_sha="$(git -C "$REPO_DIR" rev-parse HEAD)"
    log "Código recebido do GitHub: $old_sha -> $new_sha"

    if ! git -C "$REPO_DIR" diff --quiet "$old_sha" "$new_sha" -- requirements.txt; then
        log "Dependências alteradas; instalando requirements.txt."
        if ! python -m pip install -r "$REPO_DIR/requirements.txt" >> "$LOG_FILE" 2>&1; then
            git -C "$REPO_DIR" reset --hard "$old_sha" >/dev/null 2>&1
            log "FALHA ao instalar dependências; código revertido para $old_sha. Robô não foi iniciado."
            return 1
        fi
    fi

    if ! (cd "$REPO_DIR" && python -m py_compile main.py) >> "$LOG_FILE" 2>&1; then
        git -C "$REPO_DIR" reset --hard "$old_sha" >/dev/null 2>&1
        log "FALHA na verificação de sintaxe; código revertido para $old_sha."
        return 1
    fi

    if ! (cd "$REPO_DIR" && python -m unittest discover -s tests -v) >> "$LOG_FILE" 2>&1; then
        git -C "$REPO_DIR" reset --hard "$old_sha" >/dev/null 2>&1
        log "FALHA nos testes locais; código revertido para $old_sha."
        return 1
    fi

    log "ATUALIZAÇÃO VALIDADA E CONCLUÍDA. O robô não foi iniciado, parado ou reiniciado."
    return 0
}

agent_running() {
    if [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

start_agent() {
    if agent_running; then
        echo "Atualizador DEMEX já está em execução."
        return 0
    fi
    nohup bash "$SCRIPT_PATH" loop >/dev/null 2>&1 &
    echo "$!" > "$PID_FILE"
    sleep 1
    if agent_running; then
        echo "Atualizador automático iniciado. Verificação a cada ${CHECK_INTERVAL}s."
        echo "Log: $LOG_FILE"
    else
        rm -f "$PID_FILE"
        echo "Não foi possível iniciar o atualizador. Consulte: $LOG_FILE"
        return 1
    fi
}

stop_agent() {
    if ! agent_running; then
        rm -f "$PID_FILE"
        echo "Atualizador já estava parado."
        return 0
    fi
    pid="$(cat "$PID_FILE")"
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Atualizador parado. O robô DEMEX não foi afetado."
}

show_status() {
    if agent_running; then
        echo "Atualizador automático: ATIVO (PID $(cat "$PID_FILE"))."
    else
        echo "Atualizador automático: PARADO."
    fi
    if robot_is_running; then
        echo "Robô DEMEX: EM EXECUÇÃO."
    else
        echo "Robô DEMEX: PARADO."
    fi
    echo "Últimos registros:"
    tail -n 12 "$LOG_FILE" 2>/dev/null || echo "Ainda sem registros."
}

case "${1:-}" in
    instalar)
        for cmd in git curl python pgrep; do
            command -v "$cmd" >/dev/null 2>&1 || {
                echo "Comando necessário não encontrado: $cmd"
                exit 1
            }
        done
        [ -d "$REPO_DIR/.git" ] || {
            echo "Projeto não encontrado em $REPO_DIR"
            exit 1
        }
        origin="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
        case "$origin" in
            "$REPO_URL"|"https://github.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO")
                ;;
            *)
                echo "O endereço Git do projeto não corresponde ao repositório oficial. Nada foi alterado."
                exit 1
                ;;
        esac
        bash -n "$SCRIPT_PATH" || exit 1
        echo "Fazendo a primeira verificação segura..."
        update_once
        start_agent
        ;;
    loop)
        log "Agente de atualização iniciado; consulta ao GitHub a cada ${CHECK_INTERVAL}s."
        while true; do
            update_once
            sleep "$CHECK_INTERVAL"
        done
        ;;
    atualizar)
        update_once
        ;;
    status)
        show_status
        ;;
    parar)
        stop_agent
        ;;
    iniciar)
        start_agent
        ;;
    *)
        echo "Uso: bash $SCRIPT_PATH {instalar|status|atualizar|iniciar|parar}"
        exit 2
        ;;
esac
