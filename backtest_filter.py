"""Backtest historico sem lookahead para a estrategia SCRIPT AHORA."""
from __future__ import annotations
from strategies.my_strategy import get_signal


def evaluate_backtest(candles):
    """Entrada na abertura da vela seguinte; expiracao no fechamento dela.

    O ultimo candle recebido pode estar em formacao e e descartado.
    Empates nao entram no denominador da taxa de acerto.
    A aprovacao depende somente de assertividade estritamente acima de 70%;
    nao existe quantidade minima de operacoes historicas.
    """
    if not isinstance(candles, list) or len(candles) < 20:
        return {"approved": False, "reason": "historico_insuficiente",
                "trades": 0, "wins": 0, "losses": 0, "ties": 0,
                "win_rate": 0.0}
    completed = candles[:-1]
    wins = losses = ties = 0
    for signal_index in range(15, len(completed) - 1):
        sample = completed[:signal_index + 2]
        signal = get_signal(sample)
        if not signal:
            continue
        entry_candle = completed[signal_index + 1]
        try:
            op = float(entry_candle["open"])
            close = float(entry_candle["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close == op:
            ties += 1
        elif signal["direction"] == "CALL":
            if close > op:
                wins += 1
            else:
                losses += 1
        elif signal["direction"] == "PUT":
            if close < op:
                wins += 1
            else:
                losses += 1
    decisive = wins + losses
    rate = (100.0 * wins / decisive) if decisive else 0.0
    approved = decisive > 0 and rate > 70.0
    reason = ("aprovado" if approved else
              "sem_operacoes_validas" if decisive == 0 else
              "taxa_abaixo_ou_igual_70")
    return {"approved": approved, "reason": reason, "trades": decisive,
            "wins": wins, "losses": losses, "ties": ties,
            "win_rate": round(rate, 2)}
