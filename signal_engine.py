"""Configurable, read-only technical signal engine. Confidence is a confluence score, not win probability."""
from __future__ import annotations
import importlib.util
from pathlib import Path


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    out = sum(values[:period]) / period
    for value in values[period:]:
        out = alpha * value + (1 - alpha) * out
    return out


def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for a, b in zip(values[-period-1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def macd(values, fast=5, slow=25, signal=5):
    if len(values) < slow + signal:
        return None

    def series(period):
        alpha = 2 / (period + 1)
        out = [sum(values[:period]) / period]
        for value in values[period:]:
            out.append(alpha * value + (1 - alpha) * out[-1])
        return out

    fast_series = series(fast)
    slow_series = series(slow)
    offset = slow - fast
    line = [fast_series[i + offset] - slow_series[i] for i in range(len(slow_series))]
    signal_line = ema(line, signal)
    return None if signal_line is None else line[-1] - signal_line


def pattern_direction(candles, pattern):
    if len(candles) < 2:
        return None
    candle = candles[-1]
    previous = candles[-2]
    open_, high, low, close = (float(candle[k]) for k in ("open", "high", "low", "close"))
    prev_open, _, _, prev_close = (float(previous[k]) for k in ("open", "high", "low", "close"))
    body = abs(close - open_)
    candle_range = max(high - low, 1e-12)
    upper = high - max(open_, close)
    lower = min(open_, close) - low

    if pattern == "command_candle":
        if abs(open_ - low) <= candle_range * 0.0005 and close > open_:
            return "CALL"
        if abs(high - open_) <= candle_range * 0.0005 and close < open_:
            return "PUT"
    elif pattern == "engulfing":
        if close > open_ and prev_close < prev_open and open_ <= prev_close and close >= prev_open:
            return "CALL"
        if close < open_ and prev_close > prev_open and open_ >= prev_close and close <= prev_open:
            return "PUT"
    elif pattern == "doji" and body / candle_range <= 0.10:
        return "CALL" if lower > upper * 1.3 else "PUT" if upper > lower * 1.3 else None
    elif pattern == "hammer":
        if lower >= body * 2 and upper <= max(body, 1e-12) * 0.5:
            return "CALL"
        if upper >= body * 2 and lower <= max(body, 1e-12) * 0.5:
            return "PUT"
    return None


def custom_script_signal(path, candles, config):
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(f"Script personalizado não encontrado: {file}")
    spec = importlib.util.spec_from_file_location("demex_custom_strategy", file)
    if not spec or not spec.loader:
        raise ImportError("Não foi possível carregar o script personalizado.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "get_signal", None)
    if not callable(fn):
        raise ValueError("O script personalizado deve implementar get_signal(candles, config).")
    result = fn(candles, config)
    if result is None:
        return None
    if isinstance(result, str) and result in ("CALL", "PUT"):
        return {"direction": result, "confidence": 100, "reasons": ["SCRIPT PERSONALIZADO"]}
    if isinstance(result, dict):
        direction = result.get("direction")
        try:
            confidence = float(result.get("confidence", 0))
        except (TypeError, ValueError):
            return None
        if direction not in ("CALL", "PUT") or not 0 <= confidence <= 100:
            return None
        return {
            "direction": direction,
            "confidence": round(confidence),
            "reasons": result.get("reasons", ["SCRIPT PERSONALIZADO"]),
        }
    return None


def analyze(candles, config):
    if len(candles) < 30:
        return None

    if config.get("strategy_mode") == "custom_script":
        result = custom_script_signal(
            config.get("custom_script_path", "strategies/my_strategy.py"),
            candles,
            config,
        )
        if not result:
            return None
        if result["confidence"] <= int(config.get("minimum_confidence", 70)):
            return None
        return {
            "direction": result["direction"],
            "confidence": result["confidence"],
            "reasons": result.get("reasons", ["SCRIPT PERSONALIZADO"]),
            "votes": 1,
        }

    closes = [float(candle["close"]) for candle in candles]
    votes = []
    reasons = []
    indicators = config.get("indicators", {})

    fast_cfg = indicators.get("ema_fast", {})
    slow_cfg = indicators.get("ema_slow", {})
    if fast_cfg.get("enabled") and slow_cfg.get("enabled"):
        fast_value = ema(closes, int(fast_cfg.get("period", 9)))
        slow_value = ema(closes, int(slow_cfg.get("period", 21)))
        if fast_value is not None and slow_value is not None and fast_value != slow_value:
            votes.append("CALL" if fast_value > slow_value else "PUT")
            reasons.append("EMA")

    rsi_cfg = indicators.get("rsi", {})
    if rsi_cfg.get("enabled"):
        value = rsi(closes, int(rsi_cfg.get("period", 9)))
        if value is not None:
            if value <= float(rsi_cfg.get("oversold", 30)):
                votes.append("CALL")
                reasons.append("RSI")
            elif value >= float(rsi_cfg.get("overbought", 70)):
                votes.append("PUT")
                reasons.append("RSI")

    macd_cfg = indicators.get("macd", {})
    if macd_cfg.get("enabled"):
        value = macd(
            closes,
            int(macd_cfg.get("fast", 5)),
            int(macd_cfg.get("slow", 25)),
            int(macd_cfg.get("signal", 5)),
        )
        if value is not None and value != 0:
            votes.append("CALL" if value > 0 else "PUT")
            reasons.append("MACD")

    for pattern in config.get("enabled_patterns", []):
        direction = pattern_direction(candles, pattern)
        if direction:
            votes.append(direction)
            reasons.append("PADRÃO:" + pattern)

    if not votes:
        return None
    calls = votes.count("CALL")
    puts = votes.count("PUT")
    if calls == puts:
        return None

    direction = "CALL" if calls > puts else "PUT"
    confidence = round(100 * max(calls, puts) / len(votes))
    if confidence <= int(config.get("minimum_confidence", 70)):
        return None
    return {
        "direction": direction,
        "confidence": confidence,
        "reasons": sorted(set(reasons)),
        "votes": len(votes),
    }
