"""GO 2024 FILTRADO — tradução fiel do indicador Lua enviado pelo usuário.

Regras preservadas:
- Fonte MaValue=5: HL2 ((high + low) / 2), conforme a seleção usada no projeto.
- buffer1 = SMA(1) - SMA(21); buffer2 = WMA(buffer1, 3).
- EMA(21) e EMA(45) calculadas sobre close.
- ADX(14) com suavização EMA de Wilder definida no Lua: período 2*n-1 (27)
  aplicado a TR, +DM, -DM, DX e ADX.
- CALL: cruzamento ascendente, close > EMA21 > EMA45 e ADX >= 35.
- PUT: cruzamento descendente, close < EMA21 < EMA45 e ADX >= 35.

A leitura intrabar é provisória; a autorização final continua sob as validações
de vela, relógio da corretora e confirmação de ordem do DEMEX.
"""
from __future__ import annotations

FAST_PERIOD = 1
SLOW_PERIOD = 21
SIGNAL_PERIOD = 3
EMA_FILTER_PERIOD = 21
EMA_TREND_PERIOD = 45
SOURCE_SELECTION = 5
ADX_PERIOD = 14
ADX_MINIMUM = 35.0
ADX_SMOOTHING_PERIOD = 2 * ADX_PERIOD - 1


def _number(candle, key):
    try:
        value = float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _price_series(candles):
    """MaValue=5 traduzido para HL2; EMAs usam close."""
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


def _ema_series(values, period):
    """EMA com semente SMA; ignora None até encontrar uma janela válida."""
    result = [None] * len(values)
    if period < 1:
        return result
    valid_indices = []
    seed_values = []
    current = None
    alpha = 2.0 / (period + 1.0)
    for index, value in enumerate(values):
        if value is None:
            continue
        if current is None:
            seed_values.append(value)
            valid_indices.append(index)
            if len(seed_values) == period:
                current = sum(seed_values) / period
                result[index] = current
            continue
        current = alpha * value + (1.0 - alpha) * current
        result[index] = current
    return result


def _adx_series(candles, period=ADX_PERIOD):
    """Reproduz a suavização do Lua: EMA(2*period-1) em todas as séries."""
    result = [None] * len(candles)
    if period < 1 or len(candles) < 3 * period:
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

    true_ranges = []
    plus_moves = []
    minus_moves = []
    for index in range(len(candles)):
        if index == 0:
            true_ranges.append(highs[index] - lows[index])
            plus_moves.append(0.0)
            minus_moves.append(0.0)
            continue
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        plus_moves.append(
            up_move if up_move > down_move and up_move > 0 else 0.0
        )
        minus_moves.append(
            down_move if down_move > up_move and down_move > 0 else 0.0
        )
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))

    smoothing = 2 * period - 1
    smoothed_tr = _ema_series(true_ranges, smoothing)
    smoothed_plus = _ema_series(plus_moves, smoothing)
    smoothed_minus = _ema_series(minus_moves, smoothing)

    dx = [None] * len(candles)
    for index in range(len(candles)):
        tr = smoothed_tr[index]
        plus = smoothed_plus[index]
        minus = smoothed_minus[index]
        if tr is None or plus is None or minus is None:
            continue
        if tr <= 0:
            dx[index] = 0.0
            continue
        plus_di = 100.0 * plus / tr
        minus_di = 100.0 * minus / tr
        di_sum = plus_di + minus_di
        dx[index] = (
            0.0 if di_sum <= 0
            else 100.0 * abs(plus_di - minus_di) / di_sum
        )

    return _ema_series(dx, smoothing)


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
    current = (
        buffer1[index], buffer2[index], ema_filter[index],
        ema_trend[index], adx[index],
    )
    previous = (buffer1[index - 1], buffer2[index - 1])
    if any(value is None for value in current + previous):
        return None
    if adx[index] < ADX_MINIMUM:
        return None

    cross_up = (
        buffer1[index] > buffer2[index]
        and buffer1[index - 1] < buffer2[index - 1]
    )
    cross_down = (
        buffer1[index] < buffer2[index]
        and buffer1[index - 1] > buffer2[index - 1]
    )

    if (
        cross_up
        and closes[index] > ema_filter[index]
        and ema_filter[index] > ema_trend[index]
    ):
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024 FILTRADO: cruzamento ascendente SMA(1)-SMA(21) sobre WMA(3)",
                "Preço acima da EMA(21)",
                "EMA(21) acima da EMA(45)",
                "ADX(14) aprovado: {:.2f} >= {:.0f}".format(adx[index], ADX_MINIMUM),
            ],
        }

    if (
        cross_down
        and closes[index] < ema_filter[index]
        and ema_filter[index] < ema_trend[index]
    ):
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024 FILTRADO: cruzamento descendente SMA(1)-SMA(21) abaixo da WMA(3)",
                "Preço abaixo da EMA(21)",
                "EMA(21) abaixo da EMA(45)",
                "ADX(14) aprovado: {:.2f} >= {:.0f}".format(adx[index], ADX_MINIMUM),
            ],
        }
    return None


def get_signal_at_index(candles, index):
    """Calcula o sinal exatamente no candle indicado."""
    if not candles or len(candles) < 60 or index < 1 or index >= len(candles):
        return None
    return _signal_at(candles, index, "CLOSED")


def get_signal(candles, config=None):
    """Confirma o sinal na última vela fechada; descarta a última recebida."""
    if not candles or len(candles) < 61:
        return None
    closed = candles[:-1]
    return get_signal_at_index(closed, len(closed) - 1)


def get_intrabar_signal(candles, config=None):
    """Sinal provisório na vela M1 em formação."""
    if not candles or len(candles) < 60:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR")
