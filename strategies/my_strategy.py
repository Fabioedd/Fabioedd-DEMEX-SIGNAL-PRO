"""DUBAI 2023 PRO — estratégia personalizada do usuário.

Lógica original preservada:
- SMA rápida: 1 período (equivale à série de preço selecionada; aqui usamos CLOSE).
- SMA lenta: 34 períodos.
- buffer1 = SMA(1) - SMA(34).
- buffer2 = WMA(buffer1, 5).
- CALL no cruzamento de buffer1 para cima de buffer2.
- PUT no cruzamento de buffer1 para baixo de buffer2.

Únicos filtros adicionais autorizados:
- CALL somente se o fechamento estiver acima das EMA 9 e EMA 21.
- PUT somente se o fechamento estiver abaixo das EMA 9 e EMA 21.
- Se estiver entre as EMAs, não sinaliza.

Para evitar repintura, o cálculo usa somente candles fechados (ignora o último candle,
que pode estar em formação, conforme o feed da corretora).
"""

def _sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


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
    # O último candle pode ainda estar aberto. Trabalhamos com os fechados.
    if len(candles) < 36:
        return None

    closed = candles[:-1]
    closes = [float(candle["close"]) for candle in closed]

    # Filtros: EMAs 9 e 21, calculadas até o último candle fechado.
    ema9_series = _ema_series(closes, 9)
    ema21_series = _ema_series(closes, 21)
    if not ema9_series or not ema21_series:
        return None

    last_close = closes[-1]
    ema9 = ema9_series[-1]
    ema21 = ema21_series[-1]
    if ema9 is None or ema21 is None:
        return None

    # Script original: SMA(1) - SMA(34), seguido de WMA(5).
    buffer1 = []
    for index in range(len(closes)):
        history = closes[:index + 1]
        slow = _sma(history, 34)
        if slow is not None:
            fast = _sma(history, 1)
            buffer1.append(fast - slow)

    if len(buffer1) < 6:
        return None

    # Valores atual e anterior, ambos em candles fechados.
    current_buffer1 = buffer1[-1]
    previous_buffer1 = buffer1[-2]
    current_buffer2 = _wma(buffer1, 5)
    previous_buffer2 = _wma(buffer1[:-1], 5)
    if current_buffer2 is None or previous_buffer2 is None:
        return None

    # Cruzamentos exatamente na direção definida pelo script original.
    buy_cross = current_buffer1 > current_buffer2 and previous_buffer1 < previous_buffer2
    sell_cross = current_buffer1 < current_buffer2 and previous_buffer1 > previous_buffer2

    if buy_cross and last_close > ema9 and last_close > ema21:
        return {
            "direction": "CALL",
            "confidence": 100,
            "reasons": ["DUBAI 2023: cruzamento de compra", "Preço acima da EMA 9 e EMA 21"],
        }

    if sell_cross and last_close < ema9 and last_close < ema21:
        return {
            "direction": "PUT",
            "confidence": 100,
            "reasons": ["DUBAI 2023: cruzamento de venda", "Preço abaixo da EMA 9 e EMA 21"],
        }

    return None
