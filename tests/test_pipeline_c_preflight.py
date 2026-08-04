import unittest
from unittest.mock import Mock, patch

import httpx

from preprocess.pipeline_c.main import sample_preflight


class PipelineCPreflightTests(unittest.TestCase):
    def test_retries_a_transient_proxy_connect_error(self) -> None:
        response = httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>" + b"x" * 4000 + b"</html>",
            request=httpx.Request("GET", "https://example.test/"),
        )
        client = Mock()
        client.get.side_effect = [httpx.ConnectError("proxy reset"), response]
        with patch("preprocess.pipeline_c.main._preflight_client", return_value=client), \
             patch("preprocess.pipeline_c.main.time.sleep"):
            accepted, final_url, reason = sample_preflight("https://example.test/")
        self.assertTrue(accepted)
        self.assertEqual("pass", reason)
        self.assertEqual(2, client.get.call_count)


if __name__ == "__main__":
    unittest.main()
