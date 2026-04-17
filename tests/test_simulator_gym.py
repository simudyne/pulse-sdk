import unittest
from unittest.mock import MagicMock, patch


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


if __name__ == "__main__":
    unittest.main()
