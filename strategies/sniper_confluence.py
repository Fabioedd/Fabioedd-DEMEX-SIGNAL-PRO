"""SNIPER — tradução do indicador Lua para o motor Python do DEMEX.

Confluência obrigatória na mesma vela:
- GO 2024: SMA(1) - SMA(34), WMA(5) do diferencial.
- Filtros: close > EMA(21) > EMA(45) para CALL; inverso para PUT.
- Padrão de candle: Harami OU Engolfo, na mesma direção.
- MaValue=5 é mantido como HL2 ((high + low) / 2), conforme a tradução já usada
  pelo projeto; as EMAs usam close.
A confirmação fechada e a leitura intrabar compartilham a mesma regra.
"""
from __future__ import annotations

FAST_PERIOD = 1
SLOW_PERIOD = 34
SIGNAL_PERIOD = 5
EMA_FILTER_PERIOD = 21
EMA_TREND_PERIOD = 45
SOURCE_SELECTION = 5


def _number(candle, key):
    try:
        value = float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _price_series(candles):
    source, closes = [], []
    for candle in candles:
        high = _number(candle, "high")
        low = _number(candle, "low")
        close = _number(candle, "close")
        if high is None or low is None or close is None or high < low:
            return None, None
        source.append((high + low) / 2.0)
        closes.append(close)
    return source, closes


def _sma_series(values, period):
    result = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            result[index] = running / period
    return result


def _ema_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        result[index] = current
    return result


def _wma_series(values, period):
    result = [None] * len(values)
    denominator = period * (period + 1) / 2.0
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        if any(value is None for value in window):
            continue
        result[index] = sum(
            value * weight for weight, value in enumerate(window, start=1)
        ) / denominator
    return result


def candle_pattern_at(candles, index):
    """Retorna HARAMI/ENGOLFO e direção quando o padrão é válido."""
    if index < 1 or index >= len(candles):
        return None
    previous, current = candles[index - 1], candles[index]
    o1, c1 = _number(previous, "open"), _number(previous, "close")
    o2, c2 = _number(current, "open"), _number(current, "close")
    if None in (o1, c1, o2, c2):
        return None

    harami_bull = o1 > c1 and o2 < c2 and o2 > c1 and c2 < o1
    harami_bear = o1 < c1 and o2 > c2 and o2 < c1 and c2 > o1
    engulf_bull = o1 > c1 and o2 < c2 and o2 < c1 and c2 > o1
    engulf_bear = o1 < c1 and o2 > c2 and o2 > c1 and c2 < o1

    if harami_bull:
        return {"direction": "CALL", "pattern": "HARAMI"}
    if harami_bear:
        return {"direction": "PUT", "pattern": "HARAMI"}
    if engulf_bull:
        return {"direction": "CALL", "pattern": "ENGOLFO"}
    if engulf_bear:
        return {"direction": "PUT", "pattern": "ENGOLFO"}
    return None


def _calculate(candles):
    if len(candles) < EMA_TREND_PERIOD:
        return None
    source, closes = _price_series(candles)
    if source is None:
        return None

    sma_fast = _sma_series(source, FAST_PERIOD)
    sma_slow = _sma_series(source, SLOW_PERIOD)
    buffer1 = [
        None if fast is None or slow is None else fast - slow
        for fast, slow in zip(sma_fast, sma_slow)
    ]
    buffer2 = _wma_series(buffer1, SIGNAL_PERIOD)
    ema_filter = _ema_series(closes, EMA_FILTER_PERIOD)
    ema_trend = _ema_series(closes, EMA_TREND_PERIOD)
    return buffer1, buffer2, ema_filter, ema_trend, closes


def _signal_at(candles, index, stage):
    calculated = _calculate(candles)
    if calculated is None or index < 1 or index >= len(candles):
        return None

    buffer1, buffer2, ema_filter, ema_trend, closes = calculated
    current = (buffer1[index], buffer2[index], ema_filter[index], ema_trend[index])
    previous = (buffer1[index - 1], buffer2[index - 1])
    if any(value is None for value in current + previous):
        return None

    pattern = candle_pattern_at(candles, index)
    if pattern is None:
        return None

    cross_up = buffer1[index] > buffer2[index] and buffer1[index - 1] < buffer2[index - 1]
    cross_down = buffer1[index] < buffer2[index] and buffer1[index - 1] > buffer2[index - 1]

    if (
        pattern["direction"] == "CALL"
        and cross_up
        and closes[index] > ema_filter[index]
        and ema_filter[index] > ema_trend[index]
    ):
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "SNIPER: cruzamento ascendente SMA(1)-SMA(34) sobre WMA(5)",
                "Preço acima da EMA(21)",
                "EMA(21) acima da EMA(45)",
                "Padrão de alta: " + pattern["pattern"],
            ],
        }

    if (
        pattern["direction"] == "PUT"
        and cross_down
        and closes[index] < ema_filter[index]
        and ema_filter[index] < ema_trend[index]
    ):
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "SNIPER: cruzamento descendente SMA(1)-SMA(34) abaixo da WMA(5)",
                "Preço abaixo da EMA(21)",
                "EMA(21) abaixo da EMA(45)",
                "Padrão de baixa: " + pattern["pattern"],
            ],
        }
    return None


def get_signal_at_index(candles, index):
    """Calcula o sinal confirmado exatamente na vela indicada."""
    if not candles or len(candles) < EMA_TREND_PERIOD or index < 1 or index >= len(candles):
        return None
    return _signal_at(candles, index, "CLOSED")


def get_signal(candles, config=None):
    """Confirma o sinal na última vela concluída; última vela recebida é descartada."""
    if not candles or len(candles) < EMA_TREND_PERIOD + 1:
        return None
    closed = candles[:-1]
    return get_signal_at_index(closed, len(closed) - 1)


def get_intrabar_signal(candles, config=None):
    """Sinal provisório na vela M1 em formação; não autoriza ordem sozinho."""
    if not candles or len(candles) < EMA_TREND_PERIOD:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
