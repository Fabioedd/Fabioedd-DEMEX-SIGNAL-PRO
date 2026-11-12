import json
import sys
import types
import unittest
from unittest.mock import patch

# O pacote da corretora não é instalado no runner de testes do GitHub.
# Stub mínimo para testar o adaptador sem rede nem credenciais reais.
try:
    import bullexapi.stable_api  # noqa: F401
except ModuleNotFoundError:
    package = types.ModuleType("bullexapi")
    package.__path__ = []
    stable_api = types.ModuleType("bullexapi.stable_api")
    stable_api.Bullex = object
    sys.modules.setdefault("bullexapi", package)
    sys.modules.setdefault("bullexapi.stable_api", stable_api)

from bullex_connector import BullexConfig, BullexReadOnlyConnector, is_transport_error


class InitialConnectionFailureTests(unittest.TestCase):
    @patch("bullex_connector.Bullex")
    def test_empty_login_response_is_reported_as_retryable_disconnect(self, mock_bullex):
        mock_bullex.return_value.connect.side_effect = json.JSONDecodeError(
            "Expecting value", "", 0
        )
        connector = BullexReadOnlyConnector(BullexConfig("user", "password"))
        result = connector.connect()
        self.assertFalse(result["connected"])
        self.assertFalse(connector.connected)
        self.assertIn("JSONDecodeError", result["reason"])
        self.assertFalse(result["requires_2fa"])

    def test_dns_resolution_failures_are_transport_errors(self):
        error = RuntimeError(
            "HTTPSConnectionPool: NameResolutionError: Failed to resolve host"
        )
        self.assertTrue(is_transport_error(error))

    def test_unrelated_programming_errors_are_not_hidden(self):
        with patch("bullex_connector.Bullex") as mock_bullex:
            mock_bullex.return_value.connect.side_effect = ValueError("bad configuration")
            connector = BullexReadOnlyConnector(BullexConfig("user", "password"))
            with self.assertRaisesRegex(ValueError, "bad configuration"):
                connector.connect()


if __name__ == "__main__":
    unittest.main()
