"""SCRIPT AHORA DONCHIAN — níveis M15 + Donchian(20) + cor do candle.

PUT: o candle M1 toca a máxima (C1) do candle M15 em formação,
também alcança o Donchian superior calculado somente com os 20 candles M1
anteriores e fecha vermelho.

CALL: o candle M1 toca a mínima (C2) do candle M15 em formação,
também alcança o Donchian inferior calculado somente com os 20 candles M1
anteriores e fecha verde.

Não usa RSI, MACD, Bollinger, médias, pavios ou filtro de rejeição.
O sinal confirmado é calculado sobre candles M1 fechados.
"""
from __future__ import annotations

M1_SECONDS = 60
M15_SECONDS = 15 * M1_SECONDS
DONCHIAN_PERIOD = 20


def _timestamp_seconds(candle):
    """Converte timestamp da corretora para segundos Unix."""
    try:
        value = float(candle["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    return value / 1000.0 if value > 10_000_000_000 else value


def _valid_candle(candle):
    try:
        values = [float(candle[key]) for key in ("open", "high", "low", "close")]
    except (KeyError, TypeError, ValueError):
        return None
    open_price, high, low, close = values
    if high < low or high < max(open_price, close) or low > min(open_price, close):
        return None
    return open_price, high, low, close


def _m15_current_levels(candles, index):
    """Calcula C1/C2 do candle M15 atual usando os candles M1 disponíveis."""
    timestamp = _timestamp_seconds(candles[index])
    if timestamp is None:
        return None

    current_bucket = int(timestamp // M15_SECONDS) * M15_SECONDS
    highs = []
    lows = []

    # Considera somente candles do bloco M15 atual até o candle analisado.
    for candle in candles[:index + 1]:
        ts = _timestamp_seconds(candle)
        if ts is None:
            continue
        minute = int(ts // M1_SECONDS) * M1_SECONDS
        if current_bucket <= minute < current_bucket + M15_SECONDS:
            values = _valid_candle(candle)
            if values is None:
                continue
            _, high, low, _ = values
            highs.append(high)
            lows.append(low)

    if not highs or not lows:
        return None
    return max(highs), min(lows), current_bucket


def _donchian_previous(candles, index):
    """Donchian(20) usando exclusivamente os 20 candles anteriores."""
    start = index - DONCHIAN_PERIOD
    if start < 0:
        return None

    previous = candles[start:index]
    if len(previous) != DONCHIAN_PERIOD:
        return None

    highs = []
    lows = []
    for candle in previous:
        values = _valid_candle(candle)
        if values is None:
            return None
        _, high, low, _ = values
        highs.append(high)
        lows.append(low)

    return max(highs), min(lows)


def _signal_at(candles, signal_index, stage):
    """Avalia a confluência AHORA M15 + Donchian anterior + cor da vela."""
    if signal_index < DONCHIAN_PERIOD or signal_index >= len(candles):
        return None

    values = _valid_candle(candles[signal_index])
    levels = _m15_current_levels(candles, signal_index)
    channel = _donchian_previous(candles, signal_index)

    if values is None or levels is None or channel is None:
        return None

    open_price, high, low, close = values
    c1, c2, _ = levels
    donchian_upper, donchian_lower = channel

    # Mesma lógica de toque do indicador Lua.
    touched_c1 = high >= c1 and low <= c1
    touched_c2 = high >= c2 and low <= c2
    touched_upper = high >= donchian_upper
    touched_lower = low <= donchian_lower

    is_green = close > open_price
    is_red = close < open_price

    # Venda: C1 M15 + Donchian superior + candle vermelho.
    if is_red and touched_c1 and touched_upper:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "Toque na C1: máxima do M15 atual",
                "Toque no Donchian superior (20 candles anteriores)",
                "Candle M1 fechou vermelho",
            ],
        }

    # Compra: C2 M15 + Donchian inferior + candle verde.
    if is_green and touched_c2 and touched_lower:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "Toque na C2: mínima do M15 atual",
                "Toque no Donchian inferior (20 candles anteriores)",
                "Candle M1 fechou verde",
            ],
        }

    return None


def get_signal(candles, config=None):
    """Confirma o sinal na última vela M1 concluída."""
    if not candles or len(candles) < DONCHIAN_PERIOD + 2:
        return None
    closed = candles[:-1]
    return _signal_at(closed, len(closed) - 1, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Sinal provisório na vela M1 em formação; não autoriza ordem sozinho."""
    if not candles or len(candles) < DONCHIAN_PERIOD + 1:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
