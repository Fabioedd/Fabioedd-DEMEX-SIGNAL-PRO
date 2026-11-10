"""Harami_GO / CONF_TRIPLA — tradução fiel da lógica Lua para Python.

Confluência obrigatória no ÚLTIMO candle FECHADO:
1) Harami de alta/baixa formado pelos dois últimos candles fechados.
2) Cruzamento GO original: SMA(1) - SMA(34), suavizado por WMA(5).
3) Fechamento acima/abaixo da EMA(200), na direção do sinal.

A última vela recebida pelo conector é descartada por estar em formação.
Integração com o DEMEX: get_signal(candles, config).
"""

SMA_FAST_PERIOD = 1
SMA_SLOW_PERIOD = 34
GO_SIGNAL_PERIOD = 5
TREND_PERIOD = 200


def _sma_series(values, period):
    """SMA alinhada ao índice original; None durante o aquecimento."""
    result = [None] * len(values)
    if len(values) < period:
        return result
    running = sum(values[:period])
    result[period - 1] = running / period
    for index in range(period, len(values)):
        running += values[index] - values[index - period]
        result[index] = running / period
    return result


def _ema_series(values, period):
    """EMA inicializada pela média simples dos primeiros valores."""
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
    """WMA com pesos crescentes, igual à suavização do GO."""
    result = [None] * len(values)
    if len(values) < period:
        return result
    denominator = period * (period + 1) / 2.0
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        if any(value is None for value in window):
            continue
        result[index] = sum(
            value * weight
            for weight, value in enumerate(window, start=1)
        ) / denominator
    return result


def _harami_direction(parent, child):
    """Retorna CALL/PUT somente quando o corpo do candle filho fica dentro do pai."""
    parent_open = float(parent["open"])
    parent_close = float(parent["close"])
    child_open = float(child["open"])
    child_close = float(child["close"])

    bullish_harami = (
        parent_open > parent_close
        and child_open < child_close
        and child_open > parent_close
        and child_close < parent_open
    )
    bearish_harami = (
        parent_open < parent_close
        and child_open > child_close
        and child_open < parent_close
        and child_close > parent_open
    )

    if bullish_harami:
        return "CALL"
    if bearish_harami:
        return "PUT"
    return None


def get_signal(candles, config):
    """Analisa candles fechados e devolve sinal no formato esperado pelo DEMEX."""
    # O conector inclui a vela atual, ainda em formação: nunca a usamos.
    if not candles or len(candles) < TREND_PERIOD + 3:
        return None

    closed = candles[:-1]
    closes = [float(candle["close"]) for candle in closed]
    if len(closed) < TREND_PERIOD + 2:
        return None

    # Harami é formado pelos dois últimos candles já encerrados.
    parent = closed[-2]
    child = closed[-1]
    pattern = _harami_direction(parent, child)
    if pattern is None:
        return None

    # GO 2024 original: SMA rápida 1, SMA lenta 34 e WMA do buffer 5.
    sma_fast = _sma_series(closes, SMA_FAST_PERIOD)
    sma_slow = _sma_series(closes, SMA_SLOW_PERIOD)
    buffer1 = [
        (fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(sma_fast, sma_slow)
    ]
    buffer2 = _wma_series(buffer1, GO_SIGNAL_PERIOD)

    current_index = len(closed) - 1
    previous_index = current_index - 1
    current_buffer1 = buffer1[current_index]
    previous_buffer1 = buffer1[previous_index]
    current_buffer2 = buffer2[current_index]
    previous_buffer2 = buffer2[previous_index]

    if any(value is None for value in (
        current_buffer1, previous_buffer1,
        current_buffer2, previous_buffer2,
    )):
        return None

    buy_cross = (
        current_buffer1 > current_buffer2
        and previous_buffer1 <= previous_buffer2
    )
    sell_cross = (
        current_buffer1 < current_buffer2
        and previous_buffer1 >= previous_buffer2
    )

    # Filtro de tendência EMA 200 no fechamento do candle do padrão.
    ema200 = _ema_series(closes, TREND_PERIOD)[current_index]
    if ema200 is None:
        return None

    last_close = closes[current_index]
    trend_up = last_close > ema200
    trend_down = last_close < ema200

    if pattern == "CALL" and buy_cross and trend_up:
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": [
                "Harami de alta confirmado nos dois últimos candles fechados",
                "GO 2024: cruzamento de alta da SMA(1)-SMA(34) com WMA(5)",
                "Filtro de tendência: fechamento acima da EMA 200",
            ],
        }

    if pattern == "PUT" and sell_cross and trend_down:
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": [
                "Harami de baixa confirmado nos dois últimos candles fechados",
                "GO 2024: cruzamento de baixa da SMA(1)-SMA(34) com WMA(5)",
                "Filtro de tendência: fechamento abaixo da EMA 200",
            ],
        }

    return None
