"""DEMEX PRO V2 — lógica Python para o robô DEMEX.

Parâmetros do indicador original:
- EMA rápida: 7 períodos.
- EMA lenta: 25 períodos.
- Linha MACD: EMA(7) - EMA(25).
- Linha de sinal: WMA(5) da linha MACD.
- Tendência: EMA(200).
- CALL: cruzamento de alta, MACD acima de zero, preço acima da EMA 200
  e candle fechado de alta.
- PUT: cruzamento de baixa, MACD abaixo de zero, preço abaixo da EMA 200
  e candle fechado de baixa.

Integração preservada: get_signal(candles, config).
O último candle recebido é ignorado por segurança, pois pode estar em formação.
"""

MA_FAST_PERIOD = 7
MA_SLOW_PERIOD = 25
SIGNAL_PERIOD = 5
TREND_PERIOD = 200


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
    # O feed pode trazer o candle atual ainda aberto; usamos apenas os fechados.
    if not candles or len(candles) < TREND_PERIOD + 1:
        return None

    closed = candles[:-1]
    closes = [float(candle["close"]) for candle in closed]
    last_candle = closed[-1]
    last_close = float(last_candle["close"])
    last_open = float(last_candle["open"])

    ema_fast_series = _ema_series(closes, MA_FAST_PERIOD)
    ema_slow_series = _ema_series(closes, MA_SLOW_PERIOD)
    ema_trend_series = _ema_series(closes, TREND_PERIOD)

    if not ema_fast_series or not ema_slow_series or not ema_trend_series:
        return None

    macd_values = []
    for fast, slow in zip(ema_fast_series, ema_slow_series):
        if fast is not None and slow is not None:
            macd_values.append(fast - slow)

    if len(macd_values) < SIGNAL_PERIOD + 1:
        return None

    current_macd = macd_values[-1]
    previous_macd = macd_values[-2]
    current_signal = _wma(macd_values, SIGNAL_PERIOD)
    previous_signal = _wma(macd_values[:-1], SIGNAL_PERIOD)
    ema_trend = ema_trend_series[-1]

    if current_signal is None or previous_signal is None or ema_trend is None:
        return None

    trend_up = last_close > ema_trend
    trend_down = last_close < ema_trend
    macd_above_zero = current_macd > 0
    macd_below_zero = current_macd < 0
    bull_candle = last_close > last_open
    bear_candle = last_close < last_open

    buy_cross = current_macd > current_signal and previous_macd < previous_signal
    sell_cross = current_macd < current_signal and previous_macd > previous_signal

    if buy_cross and macd_above_zero and trend_up and bull_candle:
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO V2: cruzamento MACD de alta (EMA 7/25)",
                "MACD acima de zero",
                "Preço acima da EMA 200",
                "Candle fechado de alta",
            ],
        }

    if sell_cross and macd_below_zero and trend_down and bear_candle:
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO V2: cruzamento MACD de baixa (EMA 7/25)",
                "MACD abaixo de zero",
                "Preço abaixo da EMA 200",
                "Candle fechado de baixa",
            ],
        }

    return None
