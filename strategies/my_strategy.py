"""DEMEX ALFA + GO 2024 CONFLUENCIA — tradução da lógica Lua para Python.

CALL somente quando, no mesmo candle FECHADO:
- MACD DEMEX: EMA(7) - EMA(25) cruza acima da WMA(5) do MACD;
- RSI(11) acima de 50;
- candle de alta (close > open);
- GO 2024: SMA(1)-SMA(34) cruza acima da WMA(5) do buffer.

PUT aplica as condições inversas.
A última vela recebida pelo conector é descartada por estar em formação.
O seletor Lua inputs.titles com índice 5 foi mantido como HLC4:
(high + low + close + close) / 4.
Integração DEMEX: get_signal(candles, config).
"""


ALFA_FAST = 7
ALFA_SLOW = 25
ALFA_SIGNAL = 5
ALFA_RSI = 11
GO_FAST = 1
GO_SLOW = 34
GO_SIGNAL = 5


def _sma_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    running = sum(values[:period])
    result[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        result[i] = running / period
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


def _rsi_series(values, period):
    """RSI de Wilder, com inicialização pela média dos ganhos/perdas."""
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

    def rsi_value(gain, loss):
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        if gain == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    result[period] = rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[i] = rsi_value(avg_gain, avg_loss)

    return result


def _cross_up(line, signal, index):
    previous = index - 1
    return (
        line[index] is not None
        and signal[index] is not None
        and line[previous] is not None
        and signal[previous] is not None
        and line[index] > signal[index]
        and line[previous] < signal[previous]
    )


def _cross_down(line, signal, index):
    previous = index - 1
    return (
        line[index] is not None
        and signal[index] is not None
        and line[previous] is not None
        and signal[previous] is not None
        and line[index] < signal[index]
        and line[previous] > signal[previous]
    )


def get_signal(candles, config):
    """Devolve CALL/PUT apenas com confluência simultânea no candle fechado."""
    if not candles or len(candles) < 40:
        return None

    # O último candle do conector ainda está em formação: descartá-lo.
    closed = candles[:-1]
    if len(closed) < GO_SLOW + GO_SIGNAL + 2:
        return None

    opens = [float(candle["open"]) for candle in closed]
    highs = [float(candle["high"]) for candle in closed]
    lows = [float(candle["low"]) for candle in closed]
    closes = [float(candle["close"]) for candle in closed]

    # Lua inputs.titles[5]: HLC4 conforme o seletor usado no indicador.
    prices = [
        (high + low + close + close) / 4.0
        for high, low, close in zip(highs, lows, closes)
    ]

    index = len(closed) - 1

    # DEMEX ALFA: MACD EMA 7/25 com WMA 5 como linha de sinal.
    alfa_fast = _ema_series(prices, ALFA_FAST)
    alfa_slow = _ema_series(prices, ALFA_SLOW)
    alfa_macd = [
        fast - slow if fast is not None and slow is not None else None
        for fast, slow in zip(alfa_fast, alfa_slow)
    ]
    alfa_signal = _wma_series(alfa_macd, ALFA_SIGNAL)
    alfa_rsi = _rsi_series(prices, ALFA_RSI)

    alfa_buy = (
        _cross_up(alfa_macd, alfa_signal, index)
        and alfa_rsi[index] is not None
        and alfa_rsi[index] > 50
        and closes[index] > opens[index]
    )
    alfa_sell = (
        _cross_down(alfa_macd, alfa_signal, index)
        and alfa_rsi[index] is not None
        and alfa_rsi[index] < 50
        and closes[index] < opens[index]
    )

    # GO 2024: SMA 1/34; WMA 5 aplicada à diferença das médias.
    go_fast = _sma_series(prices, GO_FAST)
    go_slow = _sma_series(prices, GO_SLOW)
    go_buffer1 = [
        fast - slow if fast is not None and slow is not None else None
        for fast, slow in zip(go_fast, go_slow)
    ]
    go_buffer2 = _wma_series(go_buffer1, GO_SIGNAL)

    go_buy = _cross_up(go_buffer1, go_buffer2, index)
    go_sell = _cross_down(go_buffer1, go_buffer2, index)

    # Os dois indicadores precisam cruzar na mesma direção no mesmo candle.
    if alfa_buy and go_buy:
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": [
                "DEMEX ALFA: cruzamento de alta MACD EMA 7/25 + WMA 5",
                "DEMEX ALFA: RSI 11 acima de 50 e candle de alta",
                "GO 2024: cruzamento de alta SMA 1/34 + WMA 5",
                "Confluência simultânea confirmada em candle fechado",
            ],
        }

    if alfa_sell and go_sell:
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": [
                "DEMEX ALFA: cruzamento de baixa MACD EMA 7/25 + WMA 5",
                "DEMEX ALFA: RSI 11 abaixo de 50 e candle de baixa",
                "GO 2024: cruzamento de baixa SMA 1/34 + WMA 5",
                "Confluência simultânea confirmada em candle fechado",
            ],
        }

    return None
