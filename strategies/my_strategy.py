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
ADX_PERIOD = 14
ADX_MINIMUM = 32.0


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


def _adx_series(candles, period=ADX_PERIOD):
    """ADX de Wilder; retorna None até completar o aquecimento de 2*period."""
    result = [None] * len(candles)
    if period < 2 or len(candles) < 2 * period:
        return result

    highs, lows, closes = [], [], []
    for candle in candles:
        high = _number(candle, "high")
        low = _number(candle, "low")
        close = _number(candle, "close")
        if high is None or low is None or close is None or high < low:
            return result
        highs.append(high)
        lows.append(low)
        closes.append(close)

    true_ranges, plus_moves, minus_moves = [0.0], [0.0], [0.0]
    for index in range(1, len(candles)):
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        plus_moves.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_moves.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))

    smooth_tr = sum(true_ranges[1:period + 1])
    smooth_plus = sum(plus_moves[1:period + 1])
    smooth_minus = sum(minus_moves[1:period + 1])
    dx_values = []
    previous_adx = None

    for index in range(period, len(candles)):
        if index > period:
            smooth_tr += true_ranges[index] - smooth_tr / period
            smooth_plus += plus_moves[index] - smooth_plus / period
            smooth_minus += minus_moves[index] - smooth_minus / period

        if smooth_tr <= 0:
            dx = 0.0
        else:
            plus_di = 100.0 * smooth_plus / smooth_tr
            minus_di = 100.0 * smooth_minus / smooth_tr
            di_sum = plus_di + minus_di
            dx = 0.0 if di_sum <= 0 else 100.0 * abs(plus_di - minus_di) / di_sum

        dx_values.append(dx)
        if len(dx_values) == period:
            previous_adx = sum(dx_values) / period
            result[index] = previous_adx
        elif previous_adx is not None:
            previous_adx = ((previous_adx * (period - 1)) + dx) / period
            result[index] = previous_adx

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
    adx = _adx_series(candles, ADX_PERIOD)
    return buffer1, buffer2, ema_filter, ema_trend, closes, adx


def _signal_at(candles, index, stage):
    calculated = _calculate(candles)
    if calculated is None or index < 1 or index >= len(candles):
        return None

    buffer1, buffer2, ema_filter, ema_trend, closes, adx = calculated
    current = (buffer1[index], buffer2[index], ema_filter[index], ema_trend[index], adx[index])
    previous = (buffer1[index - 1], buffer2[index - 1])
    if any(value is None for value in current + previous):
        return None
    if adx[index] < ADX_MINIMUM:
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
                "Filtro ADX(14) aprovado: {:.2f} >= {:.0f}".format(adx[index], ADX_MINIMUM),
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
                "Filtro ADX(14) aprovado: {:.2f} >= {:.0f}".format(adx[index], ADX_MINIMUM),
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
