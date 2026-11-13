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
VENV_DIR="${REPO_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

bootstrap_python() {
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
    elif command -v python >/dev/null 2>&1; then
        command -v python
    else
        return 1
    fi
}

ensure_venv() {
    if [ -x "$VENV_PYTHON" ]; then
        return 0
    fi

    bootstrap="$(bootstrap_python)" || {
        log "ERRO: Python do Termux não encontrado; não foi possível criar .venv."
        return 1
    }

    log "Ambiente .venv ausente; criando com $bootstrap."
    if ! "$bootstrap" -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1; then
        log "ERRO: criação de .venv falhou. Instale/ative o pacote Python do Termux e tente novamente."
        return 1
    fi

    if [ ! -x "$VENV_PYTHON" ]; then
        log "ERRO: .venv foi criada, mas $VENV_PYTHON não é executável."
        return 1
    fi
    return 0
}

install_venv_requirements() {
    "$VENV_PYTHON" -m pip install -r "$REPO_DIR/requirements.txt" >> "$LOG_FILE" 2>&1
}

rollback_update() {
    local previous_sha="$1"
    if ! git -C "$REPO_DIR" reset --hard "$previous_sha" >/dev/null 2>&1; then
        log "ERRO CRÍTICO: não foi possível reverter o código para $previous_sha."
        return 1
    fi

    if [ -x "$VENV_PYTHON" ] && [ -f "$REPO_DIR/requirements.txt" ]; then
        if ! install_venv_requirements; then
            log "ERRO CRÍTICO: código revertido, mas não foi possível restaurar as dependências da versão anterior."
            return 1
        fi
    fi
    log "Código restaurado para $previous_sha."
    return 0
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

    venv_missing=false
    [ -x "$VENV_PYTHON" ] || venv_missing=true
    if ! ensure_venv; then
        rollback_update "$old_sha"
        return 1
    fi

    requirements_changed=false
    if ! git -C "$REPO_DIR" diff --quiet "$old_sha" "$new_sha" -- requirements.txt; then
        requirements_changed=true
    fi

    if [ "$venv_missing" = true ] || [ "$requirements_changed" = true ]; then
        if [ "$venv_missing" = true ]; then
            log "Ambiente virtual preparado; instalando dependências do projeto na .venv."
        else
            log "requirements.txt alterado; instalando dependências na .venv."
        fi
        if ! install_venv_requirements; then
            log "FALHA ao instalar dependências na .venv; revertendo código e restaurando requirements anterior."
            rollback_update "$old_sha"
            return 1
        fi
    fi

    # Compila somente os módulos Python realmente rastreados pelo Git.
    # Não fixa nomes de estratégias removidas ou substituídas.
    if ! (
        cd "$REPO_DIR" &&
        "$VENV_PYTHON" -c '
import py_compile
import subprocess

tracked = subprocess.check_output(
    ["git", "ls-files", "-z", "--", "*.py"]
).decode("utf-8").split(chr(0))

for path in filter(None, tracked):
    py_compile.compile(path, doraise=True)
'
    ) >> "$LOG_FILE" 2>&1; then
        log "FALHA na verificação de sintaxe dos módulos Python rastreados pelo Git; revertendo atualização."
        rollback_update "$old_sha"
        return 1
    fi

    if ! (cd "$REPO_DIR" && "$VENV_PYTHON" -m unittest discover -s tests -v) >> "$LOG_FILE" 2>&1; then
        log "FALHA nos testes com .venv; revertendo atualização."
        rollback_update "$old_sha"
        return 1
    fi

    # O Termux executa uma copia em ~/.demex-auto-update.sh.
    # Atualiza essa copia somente depois de a nova versao do repositorio passar
    # por sintaxe e testes; a versao nova sera usada no proximo ciclo/reinicio.
    if [ "$SCRIPT_PATH" != "$REPO_DIR/demex-auto-update.sh" ] && [ -f "$REPO_DIR/demex-auto-update.sh" ]; then
        updater_tmp="${SCRIPT_PATH}.new"
        if cp "$REPO_DIR/demex-auto-update.sh" "$updater_tmp" &&
           chmod 700 "$updater_tmp" &&
           mv "$updater_tmp" "$SCRIPT_PATH"; then
            log "Copia local do atualizador atualizada; a nova versao sera usada no proximo reinicio."
        else
            rm -f "$updater_tmp"
            log "AVISO: codigo do robo atualizado, mas nao foi possivel atualizar a copia local do atualizador."
        fi
    fi

    log "ATUALIZAÇÃO VALIDADA E CONCLUÍDA com .venv. O robô não foi iniciado, parado ou reiniciado."
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
    if [ -x "$VENV_PYTHON" ]; then
        echo "Ambiente Python: .venv encontrado."
        "$VENV_PYTHON" --version 2>&1
    else
        echo "Ambiente Python: .venv AUSENTE (será criado na próxima atualização)."
    fi
    echo "Últimos registros:"
    tail -n 12 "$LOG_FILE" 2>/dev/null || echo "Ainda sem registros."
}

case "${1:-}" in
    instalar)
        for cmd in git curl pgrep; do
            command -v "$cmd" >/dev/null 2>&1 || {
                echo "Comando necessário não encontrado: $cmd"
                exit 1
            }
        done
        bootstrap_python >/dev/null 2>&1 || {
            echo "Python do Termux não encontrado."
            exit 1
        }
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
