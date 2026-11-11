"""GO 2024 + RSI 14 + EMA 21 — tradução do indicador Lua para Python.

O cruzamento GO 2024 é o único gatilho. RSI, EMA 21 e linha zero são filtros.
O GO usa HLC4 (hipótese correspondente ao seletor Lua inputs.titles = 5).
RSI e EMA são calculados sobre o fechamento, conforme o script solicitado.
"""

GO_FAST = 1
GO_SLOW = 34
GO_SIGNAL = 5
RSI_PERIOD = 14
EMA_PERIOD = 21
RSI_MIDLINE = 50.0


def _sma_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    total = sum(values[:period])
    result[period - 1] = total / period
    for i in range(period, len(values)):
        total += values[i] - values[i - period]
        result[i] = total / period
    return result


def _ema_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for i in range(period, len(values)):
        current = alpha * values[i] + (1.0 - alpha) * current
        result[i] = current
    return result


def _wma_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    denominator = period * (period + 1) / 2.0
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        if any(value is None for value in window):
            continue
        result[i] = sum(
            value * weight
            for weight, value in enumerate(window, start=1)
        ) / denominator
    return result


def _rsi_wilder_series(values, period):
    result = [None] * len(values)
    if len(values) <= period:
        return result

    gains = []
    losses = []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def value_for(gain, loss):
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        if gain == 0:
            return 0.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    result[period] = value_for(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[i] = value_for(avg_gain, avg_loss)
    return result


def _cross_up(line, signal, index):
    previous = index - 1
    return (
        index > 0
        and line[index] is not None
        and signal[index] is not None
        and line[previous] is not None
        and signal[previous] is not None
        and line[index] > signal[index]
        and line[previous] < signal[previous]
    )


def _cross_down(line, signal, index):
    previous = index - 1
    return (
        index > 0
        and line[index] is not None
        and signal[index] is not None
        and line[previous] is not None
        and signal[previous] is not None
        and line[index] < signal[index]
        and line[previous] > signal[previous]
    )


def _calculate(candles):
    if not candles:
        return None

    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]

    # O índice 5 do seletor de preço da versão Lua foi tratado como HLC4.
    go_prices = [
        (high + low + close + close) / 4.0
        for high, low, close in zip(highs, lows, closes)
    ]

    fast = _sma_series(go_prices, GO_FAST)
    slow = _sma_series(go_prices, GO_SLOW)
    buffer1 = [
        a - b if a is not None and b is not None else None
        for a, b in zip(fast, slow)
    ]
    buffer2 = _wma_series(buffer1, GO_SIGNAL)

    rsi_values = _rsi_wilder_series(closes, RSI_PERIOD)
    ema_values = _ema_series(closes, EMA_PERIOD)

    return {
        "opens": opens,
        "closes": closes,
        "buffer1": buffer1,
        "buffer2": buffer2,
        "rsi": rsi_values,
        "ema21": ema_values,
    }


def _signal_at(candles, index, stage):
    data = _calculate(candles)
    if data is None or index < 1:
        return None

    line = data["buffer1"]
    signal_line = data["buffer2"]
    rsi_value = data["rsi"][index]
    ema_value = data["ema21"][index]
    close = data["closes"][index]

    if (
        line[index] is None
        or signal_line[index] is None
        or rsi_value is None
        or ema_value is None
    ):
        return None

    # GO é o gatilho. Os três critérios abaixo apenas filtram o cruzamento.
    call = (
        _cross_up(line, signal_line, index)
        and line[index] > 0.0
        and rsi_value > RSI_MIDLINE
        and close > ema_value
    )
    put = (
        _cross_down(line, signal_line, index)
        and line[index] < 0.0
        and rsi_value < RSI_MIDLINE
        and close < ema_value
    )

    if call:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024: cruzamento de alta SMA 1/34 + WMA 5",
                "GO 2024: buffer1 acima da linha zero",
                "Filtro RSI 14 acima de 50",
                "Filtro de tendência: fechamento acima da EMA 21",
            ],
        }
    if put:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "reasons": [
                "GO 2024: cruzamento de baixa SMA 1/34 + WMA 5",
                "GO 2024: buffer1 abaixo da linha zero",
                "Filtro RSI 14 abaixo de 50",
                "Filtro de tendência: fechamento abaixo da EMA 21",
            ],
        }
    return None


def get_signal(candles, config=None):
    """Sinal confirmado na última vela fechada; a última recebida é descartada."""
    if not candles or len(candles) < 60:
        return None
    closed = candles[:-1]
    if len(closed) < 40:
        return None
    return _signal_at(closed, len(closed) - 1, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Sinal na vela M1 em formação; pode desaparecer antes do fechamento."""
    if not candles or len(candles) < 60:
        return None
    return _signal_at(candles, len(candles) - 1, "INTRABAR_CONFIRMED")


def get_pre_signal(candles, config=None):
    """Pré-sinal de aproximação do cruzamento; informativo, nunca autoriza ordem."""
    if not candles or len(candles) < 60:
        return None

    data = _calculate(candles)
    index = len(candles) - 1
    previous = index - 1
    line = data["buffer1"]
    signal_line = data["buffer2"]
    rsi_value = data["rsi"][index]
    ema_value = data["ema21"][index]
    close = data["closes"][index]

    if any(
        values[index] is None or values[previous] is None
        for values in (line, signal_line)
    ) or rsi_value is None or ema_value is None:
        return None

    old_gap = line[previous] - signal_line[previous]
    new_gap = line[index] - signal_line[index]

    # Antes do cruzamento: gap se aproximando de zero, sem já ter cruzado.
    call_approach = old_gap < new_gap < 0 and rsi_value > RSI_MIDLINE and close > ema_value
    put_approach = old_gap > new_gap > 0 and rsi_value < RSI_MIDLINE and close < ema_value

    if not (call_approach or put_approach):
        return None

    direction = "CALL" if call_approach else "PUT"
    proximity = max(0.0, min(1.0, 1.0 - abs(new_gap) / max(abs(old_gap), 1e-12)))
    return {
        "direction": direction,
        "stage": "PRE_SIGNAL",
        "proximity": round(proximity, 4),
        "confidence": 0,
        "reasons": [
            "GO 2024: cruzamento se aproximando na vela em formação",
            "Filtros RSI 14 e EMA 21 favoráveis",
            "Pré-sinal informativo; não autoriza ordem",
        ],
    }
