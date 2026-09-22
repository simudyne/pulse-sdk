import json

import websocket


class GymSession:
    """A live connection to a Pulse simulator-gym environment session.

    Returned by
    :meth:`SimulatorGymResource.connect` — not constructed directly. Unlike
    every other object in this SDK the session is stateful and long-lived: it
    holds a WebSocket open and is stepped, in the style of a Gymnasium
    environment.

    Use it as a context manager so the session is closed even if stepping
    raises; otherwise call :meth:`close` yourself.

    Parameters
    ----------
    ws : websocket.WebSocket
        The open socket to the gym service.
    session_id : str
        Server-assigned id for this session.

    Attributes
    ----------
    session_id : str
        Server-assigned id for this session.

    Examples
    --------
    >>> with client.simulator_gym.connect(
    ...     symbol="700.HK", cal_date="2025-09-02", exchange="HKEX.Securities"
    ... ) as env:
    ...     obs = env.reset(seed=42)
    ...     while True:
    ...         result = env.step(0)
    ...         if result["done"]:
    ...             break
    """

    def __init__(self, ws: websocket.WebSocket, session_id: str):
        self._ws = ws
        self.session_id = session_id

    def reset(self, seed: int = None) -> dict:
        """Reset the environment and return the initial observation.

        Parameters
        ----------
        seed : int, optional
            Optional random seed for reproducibility.

        Returns
        -------
        dict
            Initial step result containing:

            - type (str): the message type, "step"
            - obs (list of float): the observation, 47 floats
            - reward (float): always 0.0 for a reset
            - done (bool): always False for a reset
            - info (dict): per-step diagnostics from the simulator

        Raises
        ------
        RuntimeError
            If the simulator replies with an error. Note this resource raises
            ``RuntimeError`` rather than ``PulseAPIError`` — it speaks
            WebSocket, not HTTP.

        Examples
        --------
        >>> obs = env.reset(seed=42)
        >>> len(obs["obs"])
        47

        Reset without a seed for a fresh random episode:

        >>> obs = env.reset()
        """
        self._ws.send(json.dumps({"type": "reset", "seed": seed}))
        msg = json.loads(self._ws.recv())
        if msg["type"] == "error":
            raise RuntimeError(f"Simulator error: {msg['message']}")
        return msg

    def step(self, action: int) -> dict:
        """Take one step in the environment.

        Parameters
        ----------
        action : int
            Integer action in range 0-13.

        Returns
        -------
        dict
            Step result containing:

            - type (str): the message type, "step"
            - obs (list of float): the observation, 47 floats
            - reward (float): reward for this step
            - done (bool): True once the episode has ended
            - info (dict): per-step diagnostics from the simulator

        Raises
        ------
        RuntimeError
            If ``action`` is outside 0-13, or the simulator replies with an
            error. Note this resource raises ``RuntimeError`` rather than
            ``PulseAPIError`` — it speaks WebSocket, not HTTP.

        Examples
        --------
        >>> result = env.step(0)
        >>> result["reward"], result["done"]
        (0.0012, False)

        Run an episode to completion, accumulating reward:

        >>> total = 0.0
        >>> obs = env.reset(seed=42)
        >>> while not obs["done"]:
        ...     obs = env.step(0)
        ...     total += obs["reward"]
        """
        self._ws.send(json.dumps({"type": "step", "action": action}))
        msg = json.loads(self._ws.recv())
        if msg["type"] == "error":
            raise RuntimeError(f"Simulator error: {msg['message']}")
        return msg

    def close(self):
        """Close the session and the underlying WebSocket connection.

        Sends a ``close`` message, waits for the acknowledgement, then shuts
        the socket down. The socket is closed even if the acknowledgement never
        arrives, so this is safe to call on a session that has already failed.
        Calling it twice is harmless.

        Called automatically when the session is used as a context manager.

        Examples
        --------
        >>> env = client.simulator_gym.connect(
        ...     symbol="700.HK", cal_date="2025-09-02", exchange="HKEX.Securities"
        ... )
        >>> try:
        ...     env.reset(seed=42)
        ... finally:
        ...     env.close()
        """
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
    """Open Gym-style reinforcement-learning environments over a WebSocket.

    Reached as ``client.simulator_gym``. The API authenticates the socket with
    your key and proxies it to the gym service, which drives the real engine.

    This is the one resource that is stateful: :meth:`connect` returns a
    :class:`GymSession` you hold open and step, rather than a dict.

    Examples
    --------
    >>> with client.simulator_gym.connect(
    ...     symbol="700.HK", cal_date="2025-09-02", exchange="HKEX.Securities"
    ... ) as env:
    ...     obs = env.reset(seed=42)
    ...     result = env.step(0)
    """

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

        Parameters
        ----------
        symbol : str
            Trading symbol, e.g. "700.HK"
        cal_date : str
            Calibration date, e.g. "2025-09-02"
        exchange : str
            Exchange identifier, e.g. "HKEX.Securities"

        Returns
        -------
        GymSession
            An open session, ready to :meth:`~GymSession.reset` and
            :meth:`~GymSession.step`. Use it as a context manager so it is
            closed on the way out.

        Raises
        ------
        RuntimeError
            If the key is rejected, the gym service cannot be reached, or the
            service refuses the session — an unknown symbol or date, most
            often. This resource raises ``RuntimeError`` rather than
            ``PulseAPIError`` because it speaks WebSocket, not HTTP.

        Notes
        -----
        ``exchange`` takes its display form here — ``"HKEX.Securities"`` — not
        the protocol slug ``"hkex_securities"`` used by
        :meth:`~simudyne.resources.simulation.SimulationResource.run` and the
        data catalog.

        Examples
        --------
        >>> with client.simulator_gym.connect(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     exchange="HKEX.Securities",
        ... ) as env:
        ...     obs = env.reset(seed=42)
        ...     result = env.step(0)
        ...     print(result["reward"], result["done"])

        Without the context manager, close it yourself:

        >>> env = client.simulator_gym.connect(
        ...     symbol="700.HK", cal_date="2025-09-02", exchange="HKEX.Securities"
        ... )
        >>> try:
        ...     env.reset(seed=42)
        ... finally:
        ...     env.close()
        """
        ws_url = f"{self._ws_base_url()}/ws/simulator-gym"
        try:
            ws = websocket.create_connection(
                ws_url,
                header={"X-API-Key": self._client.api_key},
            )
        except websocket.WebSocketBadStatusException as e:
            if "403" in str(e):
                raise RuntimeError(
                    "Authentication failed: invalid or expired API key. "
                    "Check your API key with client.api_keys.list()."
                ) from e
            raise RuntimeError(f"Failed to connect to simulator-gym: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to connect to simulator-gym: {e}") from e

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
