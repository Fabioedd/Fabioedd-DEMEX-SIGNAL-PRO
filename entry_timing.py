"""Helpers puros de seleção OTC e janela de entrada após fechamento da vela."""


def _flag(value):
    """Interpreta flags da API sem considerar a string '0' como verdadeira."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "enabled", "open"}
    return False


def _timestamp_seconds(value):
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp / 1000.0 if timestamp > 10_000_000_000 else timestamp


def is_candle_still_open(seconds_remaining):
    """True enquanto a vela de sinal ainda está em formação."""
    try:
        return float(seconds_remaining) > 0.0
    except (TypeError, ValueError):
        return False


def can_add_pending_signal(pending_count, maximum=2):
    """Limita a fila de pré-sinais sem bloquear a varredura dos ativos."""
    try:
        return int(pending_count) < int(maximum)
    except (TypeError, ValueError):
        return False


def filter_market_assets(assets, mode="OTC"):
    """Seleciona a classe de mercado configurada sem consultar payout."""
    mode = str(mode).upper()
    selected = []
    for asset in assets:
        symbol = str(asset.get("symbol", ""))
        is_otc = "OTC" in symbol.upper()
        if (mode == "OTC" and is_otc) or (mode != "OTC" and not is_otc):
            selected.append(asset)
    return selected


def is_close_confirmation_window(seconds_after_close, max_delay=3.0):
    """Autoriza a entrada da abertura até, no máximo, 3 segundos depois."""
    try:
        elapsed = float(seconds_after_close)
        limit = float(max_delay)
    except (TypeError, ValueError):
        return False
    return 0.0 <= elapsed <= limit


def is_binary_active_open(active, now_timestamp):
    """Usa flags binárias e, quando fornecida, a agenda da corretora."""
    if not isinstance(active, dict):
        return False
    if not _flag(active.get("enabled")) or _flag(active.get("is_suspended")):
        return False

    schedule = active.get("schedule")
    if schedule is None or schedule == []:
        # A API pode omitir a agenda; nesse caso, enabled + não suspenso
        # são os indicadores explícitos de disponibilidade retornados por ela.
        return True
    if not isinstance(schedule, list):
        return False

    now = _timestamp_seconds(now_timestamp)
    if now is None:
        return False

    for item in schedule:
        try:
            if isinstance(item, dict):
                start = _timestamp_seconds(item.get("open"))
                end = _timestamp_seconds(item.get("close"))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start = _timestamp_seconds(item[0])
                end = _timestamp_seconds(item[1])
            else:
                continue
            if start is not None and end is not None and start <= now <= end:
                return True
        except (TypeError, ValueError):
            continue
    return False
