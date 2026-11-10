"""DEMEX PRO — estratégia personalizada convertida do script Lua enviado.

Regras preservadas:
- EMA rápida: 7 períodos.
- EMA lenta: 25 períodos.
- Linha MACD: EMA(7) - EMA(25).
- Linha de sinal: WMA(5) da linha MACD.
- CALL: cruzamento de alta + fechamento acima da EMA 200 + candle de alta.
- PUT: cruzamento de baixa + fechamento abaixo da EMA 200 + candle de baixa.

Para evitar sinais intrabar, o último candle recebido (potencialmente em formação)
é ignorado. O sinal é calculado somente com candles fechados.
"""


def _ema_series(values, period):
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    result = [None] * (period - 1) + [current]
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def _wma(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    denominator = period * (period + 1) / 2
    return sum(value * weight for weight, value in enumerate(window, start=1)) / denominator


def get_signal(candles, config):
    # São necessários pelo menos 200 candles fechados para calcular a EMA 200.
    # O último candle do feed é ignorado porque pode estar em formação.
    if len(candles) < 201:
        return None

    closed = candles[:-1]
    closes = [float(candle["close"]) for candle in closed]
    last_candle = closed[-1]
    last_close = float(last_candle["close"])
    last_open = float(last_candle["open"])

    ema_fast_series = _ema_series(closes, 7)
    ema_slow_series = _ema_series(closes, 25)
    ema_trend_series = _ema_series(closes, 200)

    if not ema_fast_series or not ema_slow_series or not ema_trend_series:
        return None

    # Monta a linha MACD apenas nos índices em que as duas EMAs existem.
    macd_values = []
    for fast, slow in zip(ema_fast_series, ema_slow_series):
        if fast is not None and slow is not None:
            macd_values.append(fast - slow)

    # Precisamos do valor atual e do anterior da WMA(5).
    if len(macd_values) < 6:
        return None

    current_macd = macd_values[-1]
    previous_macd = macd_values[-2]
    current_signal = _wma(macd_values, 5)
    previous_signal = _wma(macd_values[:-1], 5)
    ema_trend = ema_trend_series[-1]

    if current_signal is None or previous_signal is None or ema_trend is None:
        return None

    trend_up = last_close > ema_trend
    trend_down = last_close < ema_trend
    bull_candle = last_close > last_open
    bear_candle = last_close < last_open

    buy_cross = current_macd > current_signal and previous_macd < previous_signal
    sell_cross = current_macd < current_signal and previous_macd > previous_signal

    if buy_cross and trend_up and bull_candle:
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO: cruzamento MACD de alta (7/25)",
                "Preço acima da EMA 200",
                "Candle fechado de alta",
            ],
        }

    if sell_cross and trend_down and bear_candle:
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO: cruzamento MACD de baixa (7/25)",
                "Preço abaixo da EMA 200",
                "Candle fechado de baixa",
            ],
        }

    return None
