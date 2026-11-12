"""Seleção periódica de ativos OTC pelo backtest da estratégia ativa do DEMEX."""
from __future__ import annotations

import logging
import time

from strategies.harami_engolfo_tendencia import get_signal_at_index

logger = logging.getLogger(__name__)


def _is_transport_error(exc):
    """Detecta falhas de transporte sem importar o conector/API da corretora."""
    import errno

    transport_errnos = {
        errno.ECONNABORTED, errno.ECONNRESET, errno.ENOTCONN,
        errno.EPIPE, errno.ETIMEDOUT, errno.ECONNREFUSED,
        errno.EHOSTUNREACH, errno.ENETUNREACH,
    }
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionError, TimeoutError, EOFError)):
            return True
        if isinstance(current, OSError) and current.errno in transport_errnos:
            return True
        name = type(current).__name__.lower()
        message = str(current).lower()
        if any(token in name for token in (
            "connectionerror", "connectionclosed", "websocket",
            "timeout", "nameresolution", "maxretry"
        )) or any(token in message for token in (
            "connection reset", "connection aborted", "broken pipe",
            "websocket is already closed", "failed to resolve",
            "temporary failure in name resolution", "max retries exceeded",
            "name resolution"
        )):
            return True
        current = current.__cause__ or current.__context__
    return False


def _seconds(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 1000.0 if number > 10_000_000_000 else number


def _price(candle, key):
    try:
        value = float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None
    if value != value or abs(value) == float("inf"):
        return None
    return value


def backtest_asset(connector, asset, settings, server_timestamp=None):
    """Testa os últimos 200 candles M1 fechados; entrada na vela seguinte e expiração M1."""
    window = int(settings.get("backtest_candles_count", 200))
    warmup = int(settings.get("backtest_warmup_candles", 60))
    if window != 200:
        # A janela pedida pelo projeto é fixa em 200; a configuração só pode
        # manter esse valor para evitar uma alteração acidental de critério.
        window = 200
    if warmup < 45:
        warmup = 45

    request_count = min(1000, window + warmup + 5)
    candles = connector.get_candles(asset["symbol"], 60, request_count)
    now = _seconds(
        connector.get_server_timestamp() if server_timestamp is None else server_timestamp
    )
    if now is None:
        raise RuntimeError("Relógio da BullX indisponível durante o backtest.")

    closed = []
    for candle in candles or []:
        opened_at = _seconds(candle.get("timestamp"))
        if opened_at is not None and opened_at + 60.0 <= now:
            closed.append(candle)
    closed.sort(key=lambda item: _seconds(item.get("timestamp")) or 0.0)

    base = {
        "symbol": asset["symbol"],
        "active_id": asset["active_id"],
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "operations": 0,
        "accuracy": 0.0,
        "approved": False,
        "candles_used": min(window, len(closed)),
    }
    if len(closed) < window + warmup + 1:
        base["reason"] = (
            "Histórico insuficiente: necessários {} candles fechados "
            "({} de aquecimento + {} de sinal + 1 para avaliar o resultado); recebidos {}."
        ).format(window + warmup + 1, warmup, window, len(closed))
        return base

    first_signal_index = len(closed) - window - 1
    for index in range(first_signal_index, len(closed) - 1):
        signal = get_signal_at_index(closed, index)
        if not signal:
            continue
        next_candle = closed[index + 1]
        entry_price = _price(next_candle, "open")
        exit_price = _price(next_candle, "close")
        if entry_price is None or exit_price is None:
            continue

        direction = signal.get("direction")
        if direction == "CALL":
            outcome = "WIN" if exit_price > entry_price else "LOSS" if exit_price < entry_price else "TIE"
        elif direction == "PUT":
            outcome = "WIN" if exit_price < entry_price else "LOSS" if exit_price > entry_price else "TIE"
        else:
            continue

        if outcome == "WIN":
            base["wins"] += 1
        elif outcome == "LOSS":
            base["losses"] += 1
        else:
            base["ties"] += 1

    base["operations"] = base["wins"] + base["losses"]
    base["accuracy"] = (
        base["wins"] / base["operations"] * 100.0 if base["operations"] else 0.0
    )
    threshold = float(settings.get("minimum_backtest_accuracy", 70.0))
    base["approved"] = base["operations"] > 0 and base["accuracy"] >= threshold
    base["reason"] = (
        "Aprovado" if base["approved"] else
        "Sem operações decisivas" if base["operations"] == 0 else
        "Assertividade abaixo do mínimo"
    )
    return base


def select_qualified_assets(connector, available_assets, settings, stop_check=None):
    """Refaz o backtest de todos os ativos disponíveis e substitui a lista aprovada."""
    approved = []
    results = []
    total = len(available_assets)
    started = time.monotonic()
    durations = []

    logger.info(
        "BACKTEST OTC INICIADO | %d ativos disponíveis | 200 candles M1 fechados por ativo | "
        "aprovação a partir de %.1f%%.",
        total, float(settings.get("minimum_backtest_accuracy", 70.0))
    )

    for position, asset in enumerate(available_assets, start=1):
        if stop_check and stop_check():
            raise InterruptedError("Parada solicitada durante o backtest dos ativos OTC.")
        asset_started = time.monotonic()
        while True:
            try:
                result = backtest_asset(connector, asset, settings)
                break
            except Exception as exc:
                if _is_transport_error(exc):
                    logger.warning(
                        "Conexão interrompida no backtest de %s; reconectando antes de continuar.",
                        asset["symbol"]
                    )
                    connector.connected = False
                    connector.reconnect_forever(stop_check=stop_check)
                    continue
                result = {
                "symbol": asset["symbol"],
                "active_id": asset["active_id"],
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "operations": 0,
                "accuracy": 0.0,
                "approved": False,
                "reason": "Backtest não concluído: {}".format(exc),
            }
            logger.warning("BACKTEST FALHOU | %s | %s", asset["symbol"], exc)

        elapsed = time.monotonic() - asset_started
        durations.append(elapsed)
        results.append(result)
        if result["approved"]:
            approved.append(asset)
        logger.info(
            "BACKTEST %s/%s | %s | WIN %s | LOSS %s | TIE %s | "
            "ASSERTIVIDADE %.2f%% | %s",
            position, total, result["symbol"], result["wins"], result["losses"],
            result["ties"], result["accuracy"], result["reason"]
        )

        average = sum(durations) / len(durations)
        remaining = max(0, total - position) * average
        logger.info(
            "PROGRESSO DA SELEÇÃO OTC | %s/%s ativos | tempo decorrido %.1fs | "
            "estimativa restante %.1fs.",
            position, total, time.monotonic() - started, remaining
        )

    logger.info(
        "SELEÇÃO OTC CONCLUÍDA | %s aprovados de %s disponíveis | "
        "tempo total %.1fs. Somente os aprovados serão analisados para entradas.",
        len(approved), total, time.monotonic() - started
    )
    return approved, results
