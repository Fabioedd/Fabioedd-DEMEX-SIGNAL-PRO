"""SCRIPT AHORA RSI EXHAUSTION — tradução fiel do indicador Lua para Python/DEMEX.

Regras:
- PUT: candle verde toca C1 (máxima da vela M15 anterior) e RSI >= sobrecompra.
- CALL: candle vermelho toca C2 (mínima da vela M15 anterior) e RSI <= sobrevenda.
- RSI padrão 14, sobrecompra 70 e sobrevenda 30; parâmetros configuráveis.
- Sinais fechados usam apenas candles concluídos; pré-sinal intrabar é separado.
"""
from __future__ import annotations

M1_SECONDS = 60
M15_SECONDS = 900


def _timestamp_seconds(candle):
    raw = candle.get("timestamp")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value /= 1000.0
    return int(value)


def _previous_m15_levels(candles, signal_index):
    """C1/C2 são a máxima/mínima dos 15 candles M1 da M15 anterior."""
    if signal_index < 0 or signal_index >= len(candles):
        return None
    signal_ts = _timestamp_seconds(candles[signal_index])
    if signal_ts is None:
        return None
    current_m15_start = (signal_ts // M15_SECONDS) * M15_SECONDS
    previous_m15_start = current_m15_start - M15_SECONDS
    expected = {previous_m15_start + i * M1_SECONDS for i in range(15)}
    previous = {}
    for candle in candles[:signal_index]:
        ts = _timestamp_seconds(candle)
        if ts in expected:
            previous[ts] = candle
    if set(previous) != expected:
        return None
    try:
        highs = [float(previous[ts]["high"]) for ts in expected]
        lows = [float(previous[ts]["low"]) for ts in expected]
    except (KeyError, TypeError, ValueError):
        return None
    return max(highs), min(lows)


def _rsi_wilder(closes, period):
    """RSI padrão com suavização de Wilder, calculado até o candle avaliado."""
    if period < 2 or len(closes) <= period:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _signal_at(candles, signal_index, config, stage):
    if not candles or signal_index < 0 or signal_index >= len(candles):
        return None
    levels = _previous_m15_levels(candles, signal_index)
    if levels is None:
        return None
    try:
        closes = [float(candle["close"]) for candle in candles[:signal_index + 1]]
        candle = candles[signal_index]
        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
    except (KeyError, TypeError, ValueError):
        return None

    period = int(config.get("rsi_period", 14))
    overbought = float(config.get("rsi_overbought", 70))
    oversold = float(config.get("rsi_oversold", 30))
    rsi_value = _rsi_wilder(closes, period)
    if rsi_value is None:
        return None

    c1, c2 = levels
    is_green = close > open_price
    is_red = close < open_price
    touched_c1 = high >= c1 and low <= c1
    touched_c2 = high >= c2 and low <= c2

    if is_green and touched_c1 and rsi_value >= overbought:
        return {
            "direction": "PUT",
            "confidence": 100,
            "stage": stage,
            "rsi": round(rsi_value, 2),
            "reasons": [
                "SCRIPT AHORA RSI: candle verde tocou C1 da M15 anterior",
                "RSI em sobrecompra ({:.2f} >= {:.2f})".format(rsi_value, overbought),
            ],
        }
    if is_red and touched_c2 and rsi_value <= oversold:
        return {
            "direction": "CALL",
            "confidence": 100,
            "stage": stage,
            "rsi": round(rsi_value, 2),
            "reasons": [
                "SCRIPT AHORA RSI: candle vermelho tocou C2 da M15 anterior",
                "RSI em sobrevenda ({:.2f} <= {:.2f})".format(rsi_value, oversold),
            ],
        }
    return None


def get_signal(candles, config=None):
    """Sinal na última vela M1 fechada; descarta a vela atual em formação."""
    config = config or {}
    if not candles or len(candles) < 17:
        return None
    closed = candles[:-1]
    return _signal_at(closed, len(closed) - 1, config, "CLOSED")


def get_intrabar_signal(candles, config=None):
    """Sinal provisório na vela M1 atual; usado para entrada perto do fechamento."""
    config = config or {}
    if not candles:
        return None
    return _signal_at(candles, len(candles) - 1, config, "INTRABAR")


def get_pre_signal(candles, config=None):
    return None

def backtest_strategy(candles, config=None):
    """Backtest sem look-ahead: cada sinal fechado é avaliado pela vela M1 seguinte.

    Usa apenas candles concluídos (a última vela recebida é tratada como em formação).
    Empates são contabilizados separadamente e não entram no denominador da assertividade.
    """
    config = config or {}
    if not candles or len(candles) < 18:
        return {"signals": 0, "wins": 0, "losses": 0, "ties": 0, "accuracy": 0.0}

    completed = list(candles[:-1])
    wins = losses = ties = 0
    for signal_index in range(15, len(completed) - 1):
        # get_signal ignora a última vela do recorte; assim avalia signal_index
        # e deixa signal_index + 1 exclusivamente como resultado da operação.
        signal = get_signal(completed[:signal_index + 2], config)
        if not signal:
            continue
        try:
            next_open = float(completed[signal_index + 1]["open"])
            next_close = float(completed[signal_index + 1]["close"])
        except (KeyError, TypeError, ValueError):
            continue

        if next_close == next_open:
            ties += 1
        elif signal["direction"] == "CALL":
            wins += int(next_close > next_open)
            losses += int(next_close < next_open)
        elif signal["direction"] == "PUT":
            wins += int(next_close < next_open)
            losses += int(next_close > next_open)

    decisive = wins + losses
    accuracy = (100.0 * wins / decisive) if decisive else 0.0
    return {
        "signals": wins + losses + ties,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "accuracy": round(accuracy, 2),
    }
