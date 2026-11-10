"""Exemplo de estratégia própria: retorne direção e pontuação técnica."""
def get_signal(candles, config):
    if len(candles) < 2:
        return None
    previous, current = candles[-2], candles[-1]
    if current["close"] > current["open"] and previous["close"] < previous["open"]:
        if current["close"] > previous["open"] and current["open"] < previous["close"]:
            return {"direction": "CALL", "confidence": 75}
    if current["close"] < current["open"] and previous["close"] > previous["open"]:
        if current["close"] < previous["open"] and current["open"] > previous["close"]:
            return {"direction": "PUT", "confidence": 75}
    return None
