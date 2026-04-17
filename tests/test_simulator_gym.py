import unittest
from unittest.mock import MagicMock, patch, Mock
import requests


class TestSimulatorGymAuth(unittest.TestCase):
    """Verify WebSocket authentication uses header instead of query param."""

    @patch("simudyne.resources.simulator_gym.websocket.create_connection")
    def test_connect_uses_header_auth(self, mock_create_connection):
        mock_ws = MagicMock()
        mock_ws.recv.return_value = '{"type": "created", "session_id": "test-123"}'
        mock_create_connection.return_value = mock_ws

        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_secret123")
        client.simulator_gym.connect("700.HK", "2025-09-02", "HKEX.Securities")

        mock_create_connection.assert_called_once()
        call_args = mock_create_connection.call_args

        url = call_args[0][0]
        self.assertNotIn("api_key=", url, "API key should not be in URL query string")
        self.assertNotIn("pk_test_secret123", url, "API key should not appear in URL")

        header = call_args[1].get("header", {})
        self.assertEqual(header.get("X-API-Key"), "pk_test_secret123", "API key should be in X-API-Key header")

    @patch("simudyne.resources.simulator_gym.websocket.create_connection")
    def test_connect_url_format(self, mock_create_connection):
        mock_ws = MagicMock()
        mock_ws.recv.return_value = '{"type": "created", "session_id": "test-123"}'
        mock_create_connection.return_value = mock_ws

        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_xyz", base_url="https://api.example.com")
        client.simulator_gym.connect("700.HK", "2025-09-02", "HKEX.Securities")

        url = mock_create_connection.call_args[0][0]
        self.assertEqual(url, "wss://api.example.com/ws/simulator-gym")


class TestClientTLSVerification(unittest.TestCase):
    """Verify TLS verification is explicitly enabled."""

    def test_session_verify_enabled(self):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123")
        self.assertTrue(client.session.verify, "TLS verification should be explicitly True")


class TestTimeoutAndRetry(unittest.TestCase):
    """Verify timeout and exponential backoff behavior."""

    def test_default_timeout(self):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123")
        self.assertEqual(client.timeout, 30)

    def test_custom_timeout(self):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123", timeout=60)
        self.assertEqual(client.timeout, 60)

    def test_custom_max_retries(self):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123", max_retries=5)
        self.assertEqual(client.max_retries, 5)

    @patch("simudyne.client.time.sleep")
    def test_retries_on_503(self, mock_sleep):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123", max_retries=2)

        mock_response_fail = Mock()
        mock_response_fail.ok = False
        mock_response_fail.status_code = 503

        mock_response_ok = Mock()
        mock_response_ok.ok = True
        mock_response_ok.json.return_value = {"status": "ok"}

        client.session.request = Mock(side_effect=[mock_response_fail, mock_response_ok])

        result = client._request("GET", "/test")

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(client.session.request.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("simudyne.client.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        from simudyne import PulseABM, PulseAPIError

        client = PulseABM(api_key="pk_test_123", max_retries=2)

        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_response.json.return_value = {"detail": "Service Unavailable"}

        client.session.request = Mock(return_value=mock_response)

        with self.assertRaises(PulseAPIError) as ctx:
            client._request("GET", "/test")

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(client.session.request.call_count, 3)

    def test_no_retry_on_400(self):
        from simudyne import PulseABM, PulseAPIError

        client = PulseABM(api_key="pk_test_123", max_retries=3)

        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.json.return_value = {"detail": "Bad Request"}

        client.session.request = Mock(return_value=mock_response)

        with self.assertRaises(PulseAPIError):
            client._request("GET", "/test")

        self.assertEqual(client.session.request.call_count, 1)

    @patch("simudyne.client.time.sleep")
    def test_retries_on_429_rate_limit(self, mock_sleep):
        from simudyne import PulseABM

        client = PulseABM(api_key="pk_test_123", max_retries=2)

        mock_response_fail = Mock()
        mock_response_fail.ok = False
        mock_response_fail.status_code = 429

        mock_response_ok = Mock()
        mock_response_ok.ok = True
        mock_response_ok.json.return_value = {"data": "success"}

        client.session.request = Mock(side_effect=[mock_response_fail, mock_response_ok])

        result = client._request("GET", "/test")

        self.assertEqual(result, {"data": "success"})
        self.assertEqual(client.session.request.call_count, 2)


class TestPulseAPIError(unittest.TestCase):
    """Verify custom exception behavior."""

    def test_exception_attributes(self):
        from simudyne import PulseAPIError

        err = PulseAPIError(404, "Not Found")
        self.assertEqual(err.status_code, 404)
        self.assertEqual(err.detail, "Not Found")
        self.assertIn("404", str(err))
        self.assertIn("Not Found", str(err))


if __name__ == "__main__":
    unittest.main()
