"""Read-only adapter for the third-party bullexapi Python package.

This adapter intentionally exposes market data only. It does not place,
modify, or close trades. The upstream package is unofficial and may change.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from bullexapi.stable_api import Bullex

logger = logging.getLogger(__name__)


@dataclass
class BullexConfig:
    email: str
    password: str
    account_type: str = "PRACTICE"

    @classmethod
    def from_env(cls) -> "BullexConfig":
        email = os.getenv("BULLEX_EMAIL", "").strip()
        password = os.getenv("BULLEX_PASSWORD", "")
        if not email or not password:
            raise RuntimeError("Configure BULLEX_EMAIL e BULLEX_PASSWORD no ambiente local (.env).")
        account_type = os.getenv("BULLEX_ACCOUNT_TYPE", "PRACTICE").upper()
        if account_type not in {"PRACTICE", "REAL", "TOURNAMENT"}:
            raise ValueError("BULLEX_ACCOUNT_TYPE deve ser PRACTICE, REAL ou TOURNAMENT.")
        return cls(email=email, password=password, account_type=account_type)


class BullexReadOnlyConnector:
    """Small read-only wrapper around the documented third-party client."""

    def __init__(self, config: BullexConfig):
        self.config = config
        self.client = Bullex(config.email, config.password,
                             active_account_type=config.account_type)
        self.connected = False

    def connect(self) -> dict[str, Any]:
        status, detail = self.client.connect()
        if not status:
            # The upstream library may return the literal marker '2FA'.
            return {"connected": False, "reason": str(detail or "connection_failed"),
                    "requires_2fa": detail == "2FA"}
        self.connected = bool(self.client.check_connect())
        return {"connected": self.connected, "account_type": self.config.account_type}

    def get_assets(self) -> list[dict[str, Any]]:
        self._require_connection()
        assets = self.client.get_all_ACTIVES_OPCODE()
        return [{"symbol": str(symbol), "active_id": int(active_id)}
                for symbol, active_id in assets.items()]

    def get_candles(self, symbol: str, timeframe_seconds: int, count: int = 100) -> list[dict[str, Any]]:
        self._require_connection()
        if timeframe_seconds not in (60, 300):
            raise ValueError("Somente M1 (60s) e M5 (300s) são permitidos.")
        if not 10 <= count <= 1000:
            raise ValueError("count deve ficar entre 10 e 1000.")
        known = self.client.get_all_ACTIVES_OPCODE()
        if symbol not in known:
            raise ValueError(f"Ativo não encontrado na lista recebida da Bullex: {symbol}")
        endtime = int(self.client.get_server_timestamp())
        raw = self.client.get_candles(symbol, timeframe_seconds, count, endtime)
        if not raw:
            return []
        # Preserve upstream candle fields; normalize common names without fabricating values.
        normalized = []
        for candle in raw:
            if not isinstance(candle, dict):
                continue
            normalized.append({
                "timestamp": candle.get("from", candle.get("timestamp")),
                "open": candle.get("open"),
                "high": candle.get("max", candle.get("high")),
                "low": candle.get("min", candle.get("low")),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
                "raw": candle,
            })
        return normalized

    def get_payouts(self) -> dict[str, dict[str, float]]:
        """Return payout percentages reported by the upstream feed, not estimates."""
        self._require_connection()
        raw = self.client.get_all_profit()
        result: dict[str, dict[str, float]] = {}
        if not isinstance(raw, dict):
            return result
        for symbol, types in raw.items():
            if not isinstance(types, dict):
                continue
            result[str(symbol)] = {}
            for option_type, value in types.items():
                try:
                    numeric = float(value)
                    # bullexapi documents payout as a fraction (e.g. 0.85).
                    percent = numeric * 100 if numeric <= 1 else numeric
                    if 0 <= percent <= 100:
                        result[str(symbol)][str(option_type)] = percent
                except (TypeError, ValueError):
                    continue
        return result

    def get_open_assets(self, minimum_payout_percent: float = 80.0) -> list[dict[str, Any]]:
        """Filter listed assets by a currently reported payout; missing payout is excluded."""
        assets = self.get_assets()
        payouts = self.get_payouts()
        available = []
        for asset in assets:
            symbol = asset["symbol"]
            rates = payouts.get(symbol, {})
            best = max(rates.values(), default=0.0)
            if best >= minimum_payout_percent:
                available.append({**asset, "payout_percent": round(best, 2), "payout_types": rates})
        return available

    def _require_connection(self) -> None:
        if not self.connected or not self.client.check_connect():
            self.connected = False
            raise ConnectionError("Bullex desconectada. Nenhum dado deve ser usado para gerar sinais.")

    def close(self) -> None:
        try:
            self.client.logout()
        finally:
            self.connected = False
