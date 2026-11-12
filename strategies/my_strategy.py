"""DEMEX Alfa — cruzamento MACD 7/25/5 com filtro pela linha zero.

CALL: cruzamento do MACD para cima, com as linhas MACD e sinal abaixo de zero,
e candle verde.
PUT: cruzamento do MACD para baixo, com as linhas MACD e sinal acima de zero,
e candle vermelho.

RSI não participa da geração dos sinais.
A detecção intrabar acompanha a vela em formação; get_signal confirma a última vela fechada.
"""
from __future__ import annotations


FAST_PERIOD = 7
SLOW_PERIOD = 25
SIGNAL_PERIOD = 5


def _ema_series(values, period):
    """EMA com inicialização pela média simples dos primeiros 'period' valores."""
    if period < 1 or len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    current = sum(values[:period]) / period
    result.append(current)
    alpha = 2.0 / (period + 1.0)
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def _wma_series(values, period):
    """WMA com peso crescente para os valores mais recentes."""
    result = [None] * len(values)
    if period < 1:
        return result
    denominator = period * (period + 1) / 2.0
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        if any(value is None for value in window):
            continue
        result[index] = sum(
            value * weight for weight, value in enumerate(window, start=1)
        ) / denominator
    return result


def _macd_state(closes):
    """Retorna MACD e WMA de sinal para a vela atual e a anterior."""
    fast = _ema_series(closes, FAST_PERIOD)
    slow = _ema_series(closes, SLOW_PERIOD)
    macd_line = [
        (fast_value - slow_value)
        if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(fast, slow)
    ]
    signal_line = _wma_series(macd_line, SIGNAL_PERIOD)
    if len(closes) < 2:
        return None
    values = (macd_line[-2], signal_line[-2], macd_line[-1], signal_line[-1])
    if any(value is None for value in values):
        return None
    return values


def _signal_at(candles, signal_index, stage):
    if signal_index < 1 or signal_index >= len(candles):
        return None
    try:
        closes = [float(item["close"]) for item in candles[:signal_index + 1]]
        candle = candles[signal_index]
        open_price = float(candle["open"])
        close = float(candle["close"])
    except (KeyError, TypeError, ValueError):
        return None

    macd = _macd_state(closes)
    if macd is None:
        return None

    previous_macd, previous_signal, current_macd, current_signal = macd
    is_green = close > open_price
    is_red = close < open_price

    buy_cross_below_zero = (
        current_macd > current_signal
        and previous_macd < previous_signal
        and current_macd < 0
        and current_signal < 0
    )
    sell_cross_above_zero = (
        current_macd < current_signal
        and previous_macd > previous_signal
        and current_macd > 0
        and current_signal > 0
    )

    if buy_cross_below_zero and is_green:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "MACD 7/25 cruzou acima da WMA 5 abaixo da linha zero",
                "Candle verde",
            ],
        }
    if sell_cross_above_zero and is_red:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "MACD 7/25 cruzou abaixo da WMA 5 acima da linha zero",
                "Candle vermelho",
            ],
        }
    return None


def get_signal(candles, config=None):
    """Confirma o sinal usando a última vela M1 concluída."""
    if not candles or len(candles) < SLOW_PERIOD + SIGNAL_PERIOD + 1:
        return None
    closed = candles[:-1]
    return _signal_at(closed, len(closed) - 1, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Detecta provisoriamente o cruzamento na vela M1 em formação."""
    if not candles or len(candles) < SLOW_PERIOD + SIGNAL_PERIOD + 1:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
