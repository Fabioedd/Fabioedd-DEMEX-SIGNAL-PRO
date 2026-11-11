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
