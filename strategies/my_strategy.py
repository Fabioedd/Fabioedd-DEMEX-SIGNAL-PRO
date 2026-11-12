"""DEMEX Alfa — MACD 7/25/5 + RSI(14), portado de Lua para Python.

CALL: cruzamento MACD para cima (EMA 7 acima da EMA 25, MACD cruza acima da WMA 5),
RSI(14) estritamente abaixo de 30 e candle verde.
PUT: cruzamento MACD para baixo, RSI(14) estritamente acima de 70 e candle vermelho.

Não utiliza EMA 200, filtro de tendência, suporte/resistência ou níveis M15.
A detecção intrabar acompanha a vela em formação; get_signal confirma a última vela fechada.
"""
from __future__ import annotations


FAST_PERIOD = 7
SLOW_PERIOD = 25
SIGNAL_PERIOD = 5
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0


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


def _rsi_wilder(closes, period=RSI_PERIOD):
    """RSI com suavização de Wilder."""
    if period < 2 or len(closes) <= period:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        avg_gain = ((period - 1) * avg_gain + gains[index]) / period
        avg_loss = ((period - 1) * avg_loss + losses[index]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


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
    rsi_value = _rsi_wilder(closes, RSI_PERIOD)
    if macd is None or rsi_value is None:
        return None

    previous_macd, previous_signal, current_macd, current_signal = macd
    is_green = close > open_price
    is_red = close < open_price

    buy_cross = current_macd > current_signal and previous_macd < previous_signal
    sell_cross = current_macd < current_signal and previous_macd > previous_signal

    if buy_cross and rsi_value < OVERSOLD and is_green:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "rsi": round(rsi_value, 2),
            "reasons": [
                "MACD 7/25 cruzou acima da WMA 5",
                "RSI(14) abaixo de 30 ({:.2f})".format(rsi_value),
                "Candle verde",
            ],
        }
    if sell_cross and rsi_value > OVERBOUGHT and is_red:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "rsi": round(rsi_value, 2),
            "reasons": [
                "MACD 7/25 cruzou abaixo da WMA 5",
                "RSI(14) acima de 70 ({:.2f})".format(rsi_value),
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
