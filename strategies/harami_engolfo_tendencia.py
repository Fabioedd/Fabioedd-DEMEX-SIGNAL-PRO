"""HARAMI + ENGOLFO — tradução fiel do indicador Lua para o DEMEX.

Regras:
- Harami de alta/baixa e Engolfo de alta/baixa conforme os corpos dos dois candles.
- CALL: close > EMA(21) e EMA(21) > EMA(45).
- PUT: close < EMA(21) e EMA(21) < EMA(45).
- Não exige cruzamento SMA/WMA nem qualquer outro filtro.
"""
from __future__ import annotations

EMA_FILTER_PERIOD = 21
EMA_TREND_PERIOD = 45


def _number(candle, key):
    try:
        value = float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _ema_series(values, period):
    """EMA inicializada pela média simples dos primeiros 'period' fechamentos."""
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


def candle_pattern_at(candles, index):
    """Retorna o padrão e a direção usando exatamente as regras do Lua."""
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


def _signal_at(candles, index, stage):
    if not candles or len(candles) < EMA_TREND_PERIOD:
        return None
    if index < 1 or index >= len(candles):
        return None

    closes = [_number(candle, "close") for candle in candles]
    if any(value is None for value in closes):
        return None
    ema21 = _ema_series(closes, EMA_FILTER_PERIOD)
    ema45 = _ema_series(closes, EMA_TREND_PERIOD)
    if ema21[index] is None or ema45[index] is None:
        return None

    pattern = candle_pattern_at(candles, index)
    if pattern is None:
        return None

    if (
        pattern["direction"] == "CALL"
        and closes[index] > ema21[index]
        and ema21[index] > ema45[index]
    ):
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "pattern": pattern["pattern"],
            "reasons": [
                "Padrão de alta: " + pattern["pattern"],
                "Preço acima da EMA(21)",
                "EMA(21) acima da EMA(45)",
            ],
        }

    if (
        pattern["direction"] == "PUT"
        and closes[index] < ema21[index]
        and ema21[index] < ema45[index]
    ):
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "pattern": pattern["pattern"],
            "reasons": [
                "Padrão de baixa: " + pattern["pattern"],
                "Preço abaixo da EMA(21)",
                "EMA(21) abaixo da EMA(45)",
            ],
        }
    return None


def get_signal_at_index(candles, index):
    """Calcula o sinal confirmado exatamente no índice indicado."""
    return _signal_at(candles, index, "CLOSED")


def get_signal(candles, config=None):
    """Confirma o sinal na última vela concluída; descarta a última recebida."""
    if not candles or len(candles) < EMA_TREND_PERIOD + 1:
        return None
    closed = candles[:-1]
    return get_signal_at_index(closed, len(closed) - 1)


def get_intrabar_signal(candles, config=None):
    """Calcula o sinal provisório na vela atual/em formação."""
    if not candles:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
