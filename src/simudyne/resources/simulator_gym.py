import json

import websocket


class GymSession:
    """A live connection to a Pulse simulator-gym environment session."""

    def __init__(self, ws: websocket.WebSocket, session_id: str):
        self._ws = ws
        self.session_id = session_id

    def reset(self, seed: int = None) -> dict:
        """Reset the environment and return the initial observation.

        Args:
            seed: Optional random seed for reproducibility.

        Returns:
            dict with keys: type, obs (47 floats), reward, done, info
        """
        self._ws.send(json.dumps({"type": "reset", "seed": seed}))
        msg = json.loads(self._ws.recv())
        if msg["type"] == "error":
            raise RuntimeError(f"Simulator error: {msg['message']}")
        return msg

    def step(self, action: int) -> dict:
        """Take one step in the environment.

        Args:
            action: Integer action in range 0-13.

        Returns:
            dict with keys: type, obs (47 floats), reward, done, info
        """
        self._ws.send(json.dumps({"type": "step", "action": action}))
        msg = json.loads(self._ws.recv())
        if msg["type"] == "error":
            raise RuntimeError(f"Simulator error: {msg['message']}")
        return msg

    def close(self):
        """Close the session and the underlying WebSocket connection."""
        try:
            self._ws.send(json.dumps({"type": "close"}))
            self._ws.recv()
        finally:
            self._ws.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SimulatorGymResource:
    def __init__(self, client):
        self._client = client

    def _ws_base_url(self) -> str:
        url = self._client.base_url
        if url.startswith("https://"):
            return "wss://" + url[len("https://"):]
        if url.startswith("http://"):
            return "ws://" + url[len("http://"):]
        return url

    def connect(self, symbol: str, cal_date: str, exchange: str) -> GymSession:
        """Open a new simulator-gym session.

        Args:
            symbol:    Trading symbol, e.g. "700.HK"
            cal_date:  Calibration date, e.g. "2025-09-02"
            exchange:  Exchange identifier, e.g. "HKEX.Securities"

        Returns:
            GymSession — use as a context manager:

                with client.simulator_gym.connect("700.HK", "2025-09-02", "HKEX.Securities") as env:
                    obs = env.reset(seed=42)
                    result = env.step(0)
        """
        ws_url = f"{self._ws_base_url()}/ws/simulator-gym?api_key={self._client.api_key}"
        ws = websocket.create_connection(ws_url)

        ws.send(json.dumps({
            "type": "create",
            "config": {
                "symbol": symbol,
                "cal_date": cal_date,
                "exchange": exchange,
            }
        }))

        msg = json.loads(ws.recv())
        if msg["type"] == "error":
            ws.close()
            raise RuntimeError(f"Failed to create session: {msg['message']}")
        if msg["type"] != "created":
            ws.close()
            raise RuntimeError(f"Unexpected response type '{msg['type']}' during session creation")

        return GymSession(ws, session_id=msg["session_id"])
