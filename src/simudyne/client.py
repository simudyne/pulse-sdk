import os
import sys
import time
import requests
import io
import polars as pl
from tqdm import tqdm
import tempfile
import math

from simudyne.exceptions import PulseAPIError


class PulseABM:
    """Client for the Simudyne Pulse synthetic market data API.

    The client holds the API key and HTTP session, and exposes every endpoint
    through a resource attribute (``client.simulation``, ``client.data``, ...).
    Construct it once and reuse it; the underlying :class:`requests.Session`
    keeps connections alive across calls.

    Transient failures (HTTP 429, 502, 503, 504) and network timeouts are
    retried automatically with exponential backoff. Any other non-2xx response
    raises :class:`~simudyne.exceptions.PulseAPIError`.

    Parameters
    ----------
    api_key : str, optional
        Pulse API key (``pk_live_...``). Falls back to the ``SIMUDYNE_API_KEY``
        environment variable when omitted.
    base_url : str, optional
        API root, with no trailing slash. Falls back to the
        ``SIMUDYNE_BASE_URL`` environment variable, then to
        ``https://pulse-api.simudyne.com``.
    timeout : int, optional
        Per-request timeout in seconds. Defaults to 30.
    max_retries : int, default 3
        Retry attempts for transient errors. Backoff is ``2 ** attempt``
        seconds, so the default waits 1s, 2s then 4s before giving up.

    Attributes
    ----------
    profile : ProfileResource
        Account details, usage and download history.
    api_keys : ApiKeysResource
        Create, list and revoke API keys.
    data : DataResource
        The catalog of calibrated symbols available to simulate.
    simulation : SimulationResource
        Submit agent-based simulations and retrieve their results.
    simulator_gym : SimulatorGymResource
        Gym-style reinforcement-learning environment over a WebSocket.
    validation : ValidationResource
        Score synthetic data against real data.

    Raises
    ------
    ValueError
        If no API key is given and ``SIMUDYNE_API_KEY`` is unset.

    Examples
    --------
    Key taken from the environment:

    >>> import os
    >>> os.environ["SIMUDYNE_API_KEY"] = "pk_live_..."
    >>> client = PulseABM()

    Key passed explicitly, against a non-default deployment:

    >>> client = PulseABM(
    ...     api_key="pk_live_...",
    ...     base_url="https://pulse-api-dev.simudyne.com",
    ...     timeout=60,
    ... )
    >>> print(client.profile.get()["email"])
    'you@example.com'
    """

    DEFAULT_BASE_URL = "https://pulse-api.simudyne.com"
    DEFAULT_TIMEOUT = 30
    RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        timeout: int = None,
        max_retries: int = 3,
    ):
        self.api_key = api_key or os.getenv("SIMUDYNE_API_KEY")
        if not self.api_key:
            raise ValueError("SIMUDYNE_API_KEY is not set -> pass api_key or set SIMUDYNE_API_KEY in environment")
        self.base_url = base_url or os.getenv("SIMUDYNE_BASE_URL", self.DEFAULT_BASE_URL)
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.api_key})
        self.session.verify = True

        from simudyne.resources.profile import ProfileResource
        from simudyne.resources.api_keys import ApiKeysResource
        from simudyne.resources.data import DataResource
        from simudyne.resources.simulation import SimulationResource
        from simudyne.resources.simulator_gym import SimulatorGymResource
        from simudyne.resources.validation import ValidationResource

        self.profile = ProfileResource(self)
        self.api_keys = ApiKeysResource(self)
        self.data = DataResource(self)
        self.simulation = SimulationResource(self)
        self.simulator_gym = SimulatorGymResource(self)
        self.validation = ValidationResource(self)

    def _request_with_retries(self, method: str, url: str, **kwargs):
        """Execute request with timeout and exponential backoff for transient errors."""
        kwargs.setdefault("timeout", self.timeout)
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)

                if response.ok:
                    return response

                if response.status_code in self.RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    delay = 2 ** attempt
                    time.sleep(delay)
                    continue

                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                raise PulseAPIError(response.status_code, detail)

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = 2 ** attempt
                    time.sleep(delay)
                    continue
                raise

        raise last_exception

    def _request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retries(method, url, **kwargs)
        return response.json()
    
    def _request_csv(self, method, endpoint, **kwargs):
        PAGE_SIZE = 100000
        params = kwargs.get("params", {})

        params["limit"] = PAGE_SIZE
        params["offset"] = 0
        kwargs["params"] = params

        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retries(method, url, **kwargs)

        total_rows = int(response.headers.get("X-Total-Rows", 0))
        total_pages = math.ceil(total_rows / PAGE_SIZE) if total_rows > 0 else 1

        frames = []
        df = pl.read_csv(response.text.encode(), infer_schema_length=10000)
        frames.append(df)
        schema = df.schema

        if total_pages > 1:
            with tqdm(total=total_pages, initial=1, unit="page", desc=f"Downloading ({total_rows:,} rows)") as pbar:
                for page in range(1, total_pages):
                    params["offset"] = page * PAGE_SIZE
                    kwargs["params"] = params
                    response = self._request_with_retries(method, url, **kwargs)
                    df = pl.read_csv(response.text.encode(), schema_overrides=schema, infer_schema_length=10000)
                    if df.is_empty():
                        break
                    frames.append(df)
                    pbar.update(1)

        result = pl.concat(frames) if len(frames) > 1 else frames[0]
        print(f"Done: {result.shape[0]:,} rows, {result.shape[1]} columns", file=sys.stderr)
        return result