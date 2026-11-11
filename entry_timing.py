"""Pure helpers for DEMEX candle-close confirmation and payout-free market selection."""


def is_candle_still_open(seconds_remaining):
    """True while the signal candle is forming; never authorizes an order."""
    try:
        return float(seconds_remaining) > 0.0
    except (TypeError, ValueError):
        return False


def can_add_pending_signal(pending_count, maximum=3):
    """Limits simultaneous provisional signals without blocking market scanning."""
    try:
        return int(pending_count) < int(maximum)
    except (TypeError, ValueError):
        return False


def filter_market_assets(assets, mode="OTC"):
    """Filter only the selected market class; never inspects payout."""
    mode = str(mode).upper()
    selected = []
    for asset in assets:
        symbol = str(asset.get("symbol", ""))
        is_otc = "OTC" in symbol.upper()
        if (mode == "OTC" and is_otc) or (mode != "OTC" and not is_otc):
            selected.append(asset)
    return selected


def is_close_confirmation_window(seconds_after_close, max_delay=0.75):
    """Allows only a tiny feed-publication delay, never a next-candle entry window."""
    try:
        elapsed = float(seconds_after_close)
        limit = float(max_delay)
    except (TypeError, ValueError):
        return False
    return 0.0 <= elapsed <= limit


def is_binary_active_open(active, now_timestamp):
    """Confirma disponibilidade binária por enabled, suspensão e agenda da corretora."""
    if not isinstance(active, dict):
        return False
    if not bool(active.get("enabled")) or bool(active.get("is_suspended")):
        return False
    schedule = active.get("schedule")
    if not isinstance(schedule, list) or not schedule:
        return True
    try:
        now = float(now_timestamp)
    except (TypeError, ValueError):
        return False
    for item in schedule:
        try:
            if isinstance(item, dict):
                start, end = float(item.get("open", 0)), float(item.get("close", 0))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end = float(item[0]), float(item[1])
            else:
                continue
            if start <= now <= end:
                return True
        except (TypeError, ValueError):
            continue
    return False


def is_intrabar_entry(stage):
    """Autoriza execução imediata somente para sinal detectado na vela atual em formação."""
    return str(stage).upper() == "INTRABAR"
