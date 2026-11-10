"""Exemplo de estratégia própria. Substitua pelas regras do seu indicador/script."""
def get_signal(candles, config):
    if len(candles) < 2:
        return None
    previous, current = candles[-2], candles[-1]
    if current["close"] > current["open"] and previous["close"] < previous["open"]:
        if current["close"] > previous["open"] and current["open"] < previous["close"]:
            return "CALL"
    if current["close"] < current["open"] and previous["close"] > previous["open"]:
        if current["close"] < previous["open"] and current["open"] > previous["close"]:
            return "PUT"
    return None
