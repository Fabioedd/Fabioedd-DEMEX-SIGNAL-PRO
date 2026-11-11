"""Pure helpers for DEMEX entry timing and payout-free market selection."""


def is_intrabar_entry_window(seconds_remaining):
    """True only from 3.0 through 2.0 seconds before the M1 candle closes."""
    try:
        remaining = float(seconds_remaining)
    except (TypeError, ValueError):
        return False
    return 2.0 <= remaining <= 3.0


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


def closed_signal_entry_mode(seconds_after_close):
    """Choose close entry, up-to-5-second next-candle window, or reject late signal."""
    try:
        elapsed = float(seconds_after_close)
    except (TypeError, ValueError):
        return None
    if 0.0 <= elapsed <= 0.75:
        return "CLOSE"
    if 0.75 < elapsed <= 5.0:
        return "NEXT_CANDLE_DELAY"
    return None


def is_candle_still_open(seconds_remaining):
    """True while the signal candle is still forming; never authorizes an order."""
    try:
        return float(seconds_remaining) > 0.0
    except (TypeError, ValueError):
        return False
