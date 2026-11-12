"""GO 2024 — tradução fiel do indicador Lua para o motor Python do DEMEX.

Lógica original preservada:
- SMA rápida: 1 período.
- SMA lenta: 34 períodos.
- buffer1 = SMA rápida - SMA lenta.
- buffer2 = WMA de buffer1: 5 períodos.
- EMA de preço: 21 períodos.
- EMA de tendência: 45 períodos.
- CALL: cruzamento ascendente + fechamento acima da EMA21 + EMA21 acima da EMA45.
- PUT: cruzamento descendente + fechamento abaixo da EMA21 + EMA21 abaixo da EMA45.

O seletor original MaValue=5 (inputs.titles) é traduzido para HL2
((high + low) / 2), mantendo close como fonte dos filtros EMA, como no Lua.
get_signal confirma a última vela fechada; get_intrabar_signal é provisório.
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
    """Fonte MaValue=5: HL2; filtros EMA usam close."""
    source = []
    closes = []
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

    cross_up = buffer1[index] > buffer2[index] and buffer1[index - 1] < buffer2[index - 1]
    cross_down = buffer1[index] < buffer2[index] and buffer1[index - 1] > buffer2[index - 1]

    if cross_up and closes[index] > ema_filter[index] and ema_filter[index] > ema_trend[index]:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024: cruzamento ascendente SMA(1)-SMA(34) sobre WMA(5)",
                "Preço acima da EMA(21)",
                "EMA(21) acima da EMA(45)",
            ],
        }

    if cross_down and closes[index] < ema_filter[index] and ema_filter[index] < ema_trend[index]:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024: cruzamento descendente SMA(1)-SMA(34) abaixo da WMA(5)",
                "Preço abaixo da EMA(21)",
                "EMA(21) abaixo da EMA(45)",
            ],
        }

    return None


def get_signal_at_index(candles, index):
    """Calcula o sinal confirmado exatamente na vela indicada pelo timestamp."""
    if not candles or len(candles) < EMA_TREND_PERIOD or index < 1 or index >= len(candles):
        return None
    return _signal_at(candles, index, "CLOSED")


def get_signal(candles, config=None):
    """Confirma o cruzamento na última vela M1 concluída."""
    if not candles or len(candles) < EMA_TREND_PERIOD + 1:
        return None
    closed = candles[:-1]
    return get_signal_at_index(closed, len(closed) - 1)


def get_intrabar_signal(candles, config=None):
    """Calcula sinal provisório na vela M1 em formação; não autoriza ordem sozinho."""
    if not candles or len(candles) < EMA_TREND_PERIOD:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
