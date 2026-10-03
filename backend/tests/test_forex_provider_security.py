import unittest
from unittest.mock import patch

import requests

from providers.forex_provider import ForexProvider


class ForexProviderSecurityTests(unittest.TestCase):
    def test_http_error_never_logs_api_key(self):
        key = "fake-secret-token-for-test"
        provider = ForexProvider("twelvedata", key)
        provider._throttle.acquire = lambda: None
        error = requests.HTTPError(
            f"429 Client Error for url: https://api.twelvedata.com/time_series?apikey={key}"
        )
        with patch("providers.forex_provider.requests.get", side_effect=error):
            with self.assertLogs("VertexForexProvider", level="WARNING") as captured:
                provider.get_candles("EURUSD")

        self.assertNotIn(key, "\n".join(captured.output))
        self.assertNotIn(key, provider.last_error)
        self.assertIn("apikey=***", captured.output[0])

    def test_quote_error_never_logs_api_key_even_outside_url(self):
        key = "fake-secret-token-for-test"
        provider = ForexProvider("twelvedata", key)
        provider._throttle.acquire = lambda: None
        with patch("providers.forex_provider.requests.get", side_effect=RuntimeError(f"request failed: {key}")):
            with self.assertLogs("VertexForexProvider", level="WARNING") as captured:
                provider.get_quote("EURUSD")

        self.assertNotIn(key, "\n".join(captured.output))
        self.assertNotIn(key, provider.last_error)
