"""SCRIPT AHORA — tradução fiel do indicador Lua para Python/DEMEX.

Regras originais preservadas:
- VENDA (PUT): candle verde toca/cruza a máxima C1 da vela M15 anterior.
- COMPRA (CALL): candle vermelho toca/cruza a mínima C2 da vela M15 anterior.
- "Tocar" mantém a condição original: high >= nível e low <= nível.
- Sem EMA, RSI, filtro de corpo ou filtros extras.

O DEMEX recebe candles M1. C1/C2 são reconstruídas agrupando os quinze
candles M1 completos da vela M15 anterior. Sinais para ordens usam
somente o último candle M1 fechado.
"""
from __future__ import annotations

M1_SECONDS = 60
M15_SECONDS = 900


def _timestamp_seconds(candle):
    """Lê timestamp Unix em segundos; também aceita milissegundos."""
    raw = candle.get("timestamp")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value /= 1000.0
    return int(value)


def _previous_m15_levels(candles, signal_index):
    """Retorna (C1, C2) da M15 imediatamente anterior ao candle do sinal."""
    if signal_index < 0 or signal_index >= len(candles):
        return None
    signal_ts = _timestamp_seconds(candles[signal_index])
    if signal_ts is None:
        return None

    current_m15_start = (signal_ts // M15_SECONDS) * M15_SECONDS
    previous_m15_start = current_m15_start - M15_SECONDS
    expected_starts = {
        previous_m15_start + offset * M1_SECONDS for offset in range(15)
    }
    previous_candles = {}
    for candle in candles[:signal_index]:
        ts = _timestamp_seconds(candle)
        if ts in expected_starts:
            previous_candles[ts] = candle
    if set(previous_candles) != expected_starts:
        return None
    try:
        highs = [float(candle.get("high")) for candle in previous_candles.values()]
        lows = [float(candle.get("low")) for candle in previous_candles.values()]
    except (TypeError, ValueError):
        return None
    return max(highs), min(lows)


def _signal_at(candles, signal_index, stage):
    if not candles or signal_index < 0 or signal_index >= len(candles):
        return None
    levels = _previous_m15_levels(candles, signal_index)
    if levels is None:
        return None
    c1, c2 = levels
    candle = candles[signal_index]
    try:
        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
    except (KeyError, TypeError, ValueError):
        return None

    is_green = close > open_price
    is_red = close < open_price
    touched_c1 = high >= c1 and low <= c1
    touched_c2 = high >= c2 and low <= c2

    if is_green and touched_c1:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "SCRIPT AHORA: candle verde tocou a máxima C1 da M15 anterior",
                "C1 reconstruída pelos quinze candles M1 completos anteriores",
            ],
        }
    if is_red and touched_c2:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "SCRIPT AHORA: candle vermelho tocou a mínima C2 da M15 anterior",
                "C2 reconstruída pelos quinze candles M1 completos anteriores",
            ],
        }
    return None


def get_signal(candles, config=None):
    """Sinal confirmado no último candle M1 fechado; ignora o candle em formação."""
    if not candles or len(candles) < 17:
        return None
    closed = candles[:-1]
    return _signal_at(closed, len(closed) - 1, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Diagnóstico opcional no candle M1 atual; pode mudar antes do fechamento."""
    if not candles:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")


def get_pre_signal(candles, config=None):
    """SCRIPT AHORA não define pré-sinal; não inventa gatilhos antecipados."""
    return None
