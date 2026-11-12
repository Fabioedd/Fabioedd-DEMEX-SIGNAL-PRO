"""SCRIPT AHORA BB — Bandas de Bollinger + retração + níveis M15.

PUT: toca a banda superior, faz retração confirmada e depois toca C1
(máxima do candle M15 anterior) em candle verde.
CALL: toca a banda inferior, faz retração confirmada e depois toca C2
(mínima do candle M15 anterior) em candle vermelho.

O sinal operacional é calculado somente sobre candles fechados em get_signal.
get_intrabar_signal existe apenas para diagnóstico/antecipação e é revalidado
pelo fluxo principal antes de qualquer ordem.
"""
from __future__ import annotations

from math import sqrt


BB_PERIOD = 20
BB_DEVIATION = 2.0
M1_SECONDS = 60
M15_SECONDS = 15 * M1_SECONDS
SEQUENCE_MAX_AGE = 15


def _timestamp_seconds(candle):
    """Converte timestamp da corretora para segundos Unix."""
    try:
        value = float(candle["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    return value / 1000.0 if value > 10_000_000_000 else value


def _m15_previous_levels(candles, index):
    """Reconstrói C1/C2 do M15 anterior usando 15 candles M1 completos."""
    timestamp = _timestamp_seconds(candles[index])
    if timestamp is None:
        return None

    current_bucket = int(timestamp // M15_SECONDS) * M15_SECONDS
    previous_start = current_bucket - M15_SECONDS
    previous_end = current_bucket

    group = {}
    for candle in candles[:index + 1]:
        ts = _timestamp_seconds(candle)
        if ts is None:
            continue
        minute = int(ts // M1_SECONDS) * M1_SECONDS
        if previous_start <= minute < previous_end:
            group[minute] = candle

    expected = [previous_start + offset * M1_SECONDS for offset in range(15)]
    if any(minute not in group for minute in expected):
        return None

    try:
        highs = [float(group[minute]["high"]) for minute in expected]
        lows = [float(group[minute]["low"]) for minute in expected]
    except (KeyError, TypeError, ValueError):
        return None

    return max(highs), min(lows), current_bucket


def _bollinger_at(closes, index):
    """Bandas SMA(20) +/- 2 desvios-padrão populacionais."""
    start = index - BB_PERIOD + 1
    if start < 0:
        return None

    window = closes[start:index + 1]
    if len(window) != BB_PERIOD:
        return None

    middle = sum(window) / BB_PERIOD
    variance = sum((value - middle) ** 2 for value in window) / BB_PERIOD
    deviation = sqrt(variance)
    return middle + BB_DEVIATION * deviation, middle - BB_DEVIATION * deviation


def _valid_candle(candle):
    try:
        values = [float(candle[key]) for key in ("open", "high", "low", "close")]
    except (KeyError, TypeError, ValueError):
        return None
    open_price, high, low, close = values
    if high < low or high < max(open_price, close) or low > min(open_price, close):
        return None
    return open_price, high, low, close


def _signal_at(candles, signal_index, stage):
    if signal_index < BB_PERIOD - 1 or signal_index >= len(candles):
        return None

    try:
        closes = [float(item["close"]) for item in candles[:signal_index + 1]]
    except (KeyError, TypeError, ValueError):
        return None

    upper_state = 0
    lower_state = 0
    upper_touch_index = None
    lower_touch_index = None
    upper_pullback_index = None
    lower_pullback_index = None
    active_bucket = None

    for index in range(BB_PERIOD - 1, signal_index + 1):
        candle = candles[index]
        values = _valid_candle(candle)
        levels = _m15_previous_levels(candles, index)
        bands = _bollinger_at(closes, index)

        if values is None or levels is None or bands is None:
            upper_state = lower_state = 0
            active_bucket = None
            continue

        open_price, high, low, close = values
        c1, c2, bucket = levels
        bb_upper, bb_lower = bands

        # A sequência precisa acontecer dentro do mesmo bloco M15.
        if active_bucket is not None and bucket != active_bucket:
            upper_state = lower_state = 0
            upper_touch_index = lower_touch_index = None
            upper_pullback_index = lower_pullback_index = None
        active_bucket = bucket

        previous_close = closes[index - 1] if index > 0 else close
        touched_c1 = high >= c1 and low <= c1
        touched_c2 = high >= c2 and low <= c2
        is_green = close > open_price
        is_red = close < open_price

        # PUT: banda superior -> retração para baixo -> toque em C1.
        if upper_state == 0 and high >= bb_upper:
            upper_state = 1
            upper_touch_index = index
        elif upper_state == 1:
            if (
                index > upper_touch_index
                and close < bb_upper
                and close < previous_close
            ):
                upper_state = 2
                upper_pullback_index = index
            elif index - upper_touch_index > SEQUENCE_MAX_AGE:
                upper_state = 0
                upper_touch_index = None

        sell_now = (
            upper_state == 2
            and index > upper_pullback_index
            and touched_c1
            and is_green
        )

        # CALL: banda inferior -> retração para cima -> toque em C2.
        if lower_state == 0 and low <= bb_lower:
            lower_state = 1
            lower_touch_index = index
        elif lower_state == 1:
            if (
                index > lower_touch_index
                and close > bb_lower
                and close > previous_close
            ):
                lower_state = 2
                lower_pullback_index = index
            elif index - lower_touch_index > SEQUENCE_MAX_AGE:
                lower_state = 0
                lower_touch_index = None

        buy_now = (
            lower_state == 2
            and index > lower_pullback_index
            and touched_c2
            and is_red
        )

        if sell_now and index == signal_index:
            return {
                "direction": "PUT",
                "confidence": 100,
                "stage": stage,
                "reasons": [
                    "Toque na banda superior de Bollinger (20/2)",
                    "Retração para baixo confirmada após o toque",
                    "Toque na C1: máxima do M15 anterior",
                    "Candle de confirmação verde",
                ],
            }

        if buy_now and index == signal_index:
            return {
                "direction": "CALL",
                "confidence": 100,
                "stage": stage,
                "reasons": [
                    "Toque na banda inferior de Bollinger (20/2)",
                    "Retração para cima confirmada após o toque",
                    "Toque na C2: mínima do M15 anterior",
                    "Candle de confirmação vermelho",
                ],
            }

        # Uma sequência concluída ou vencida não pode gerar sinal repetido.
        if sell_now or (upper_state and upper_touch_index is not None
                        and index - upper_touch_index > SEQUENCE_MAX_AGE):
            upper_state = 0
            upper_touch_index = upper_pullback_index = None

        if buy_now or (lower_state and lower_touch_index is not None
                       and index - lower_touch_index > SEQUENCE_MAX_AGE):
            lower_state = 0
            lower_touch_index = lower_pullback_index = None

    return None


def get_signal(candles, config=None):
    """Confirma o sinal na última vela M1 concluída."""
    if not candles or len(candles) < BB_PERIOD + 14:
        return None
    closed = candles[:-1]
    return _signal_at(closed, len(closed) - 1, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Sinal provisório na vela M1 em formação; não autoriza ordem sozinho."""
    if not candles or len(candles) < BB_PERIOD + 16:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
