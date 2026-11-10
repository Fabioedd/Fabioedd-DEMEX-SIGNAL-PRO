"""DEMEX PRO V4 ADX — tradução Python do indicador Lua enviado.

Regras preservadas:
- EMA rápida 7 e EMA lenta 25.
- MACD = EMA(7) - EMA(25); sinal = WMA(5) do MACD.
- Filtro de tendência EMA 200.
- ADX 14 com suavização EMA(27), mínimo 25.
- CALL: cruzamento MACD para cima, MACD acima de zero, preço acima
  da EMA 200, candle fechado de alta, ADX acima do mínimo e +DI > -DI.
- PUT: condições inversas.
- O último candle recebido é ignorado por segurança (pode estar aberto).

Integração: get_signal(candles, config).
"""

MA_FAST_PERIOD = 7
MA_SLOW_PERIOD = 25
SIGNAL_PERIOD = 5
TREND_PERIOD = 200
ADX_PERIOD = 14
ADX_MIN = 25
ADX_SMOOTH_PERIOD = 2 * ADX_PERIOD - 1


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


def _adx_components(candles):
    """Calcula +DI, -DI e ADX com suavização EMA(2n-1), como no Lua."""
    if len(candles) < ADX_SMOOTH_PERIOD + 2:
        return None

    true_ranges = []
    plus_dm = []
    minus_dm = []

    for previous, current in zip(candles[:-1], candles[1:]):
        prev_close = float(previous["close"])
        high = float(current["high"])
        low = float(current["low"])
        prev_high = float(previous["high"])
        prev_low = float(previous["low"])

        up_move = high - prev_high
        down_move = prev_low - low

        true_ranges.append(max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        ))
        plus_dm.append(max(up_move, 0.0) if up_move > down_move else 0.0)
        minus_dm.append(max(down_move, 0.0) if down_move > up_move else 0.0)

    tr_s = _ema_series(true_ranges, ADX_SMOOTH_PERIOD)
    plus_s = _ema_series(plus_dm, ADX_SMOOTH_PERIOD)
    minus_s = _ema_series(minus_dm, ADX_SMOOTH_PERIOD)
    if not tr_s or not plus_s or not minus_s:
        return None

    dx_values = []
    latest_plus_di = latest_minus_di = None
    for tr_value, plus_value, minus_value in zip(tr_s, plus_s, minus_s):
        if tr_value is None or plus_value is None or minus_value is None:
            dx_values.append(None)
            continue
        if tr_value <= 0:
            plus_di = minus_di = 0.0
        else:
            plus_di = 100.0 * plus_value / tr_value
            minus_di = 100.0 * minus_value / tr_value
        total_di = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / total_di if total_di > 0 else 0.0
        dx_values.append(dx)
        latest_plus_di = plus_di
        latest_minus_di = minus_di

    valid_dx = [value for value in dx_values if value is not None]
    adx_series = _ema_series(valid_dx, ADX_SMOOTH_PERIOD)
    if not adx_series or adx_series[-1] is None:
        return None
    if latest_plus_di is None or latest_minus_di is None:
        return None
    return adx_series[-1], latest_plus_di, latest_minus_di


def get_signal(candles, config):
    # O feed pode trazer a vela atual ainda aberta; a estratégia usa só velas fechadas.
    if not candles or len(candles) < TREND_PERIOD + 2:
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
    adx_data = _adx_components(closed)

    if (current_signal is None or previous_signal is None
            or ema_trend is None or adx_data is None):
        return None

    adx_value, plus_di, minus_di = adx_data
    adx_ok = adx_value > ADX_MIN
    di_up = plus_di > minus_di
    di_down = minus_di > plus_di

    trend_up = last_close > ema_trend
    trend_down = last_close < ema_trend
    macd_above_zero = current_macd > 0
    macd_below_zero = current_macd < 0
    bull_candle = last_close > last_open
    bear_candle = last_close < last_open

    buy_cross = current_macd > current_signal and previous_macd < previous_signal
    sell_cross = current_macd < current_signal and previous_macd > previous_signal

    if (buy_cross and macd_above_zero and trend_up and bull_candle
            and adx_ok and di_up):
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO V4 ADX: cruzamento MACD de alta (EMA 7/25 + WMA 5)",
                "MACD acima de zero",
                "Preço acima da EMA 200",
                "Candle fechado de alta",
                f"ADX {adx_value:.1f} acima de {ADX_MIN}",
                "+DI acima de -DI",
            ],
        }

    if (sell_cross and macd_below_zero and trend_down and bear_candle
            and adx_ok and di_down):
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": [
                "DEMEX PRO V4 ADX: cruzamento MACD de baixa (EMA 7/25 + WMA 5)",
                "MACD abaixo de zero",
                "Preço abaixo da EMA 200",
                "Candle fechado de baixa",
                f"ADX {adx_value:.1f} acima de {ADX_MIN}",
                "-DI acima de +DI",
            ],
        }

    return None
