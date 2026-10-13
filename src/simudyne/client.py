import os
import sys
import time
import requests
import io
import polars as pl
from tqdm import tqdm
import tempfile
import math

from simudyne.exceptions import PulseAPIError, error_from_response  # noqa: F401


def _never_reached_server(error: Exception) -> bool:
    """Whether a transport error happened before the request was sent.

    A connect timeout, a refused connection or a failed DNS lookup means the
    API never saw the request, so even a submit is safe to send again. A
    read timeout or a dropped connection may come after the API acted.
    """
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(error, requests.exceptions.ConnectionError):
        from urllib3.exceptions import NewConnectionError

        seen = set()
        cause = error
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, NewConnectionError):
                return True
            reason = getattr(cause, "reason", None)
            nested = cause.args[0] if getattr(cause, "args", None) else None
            cause = reason or (nested if isinstance(nested, BaseException) else None) or cause.__cause__
    return False


class PulseABM:
    """Client for the Simudyne Pulse synthetic market data API.

    The client holds the API key and HTTP session, and exposes every endpoint
    through a resource attribute (``client.simulation``, ``client.data``, ...).
    Construct it once and reuse it; the underlying :class:`requests.Session`
    keeps connections alive across calls.

    Transient failures are retried automatically with exponential backoff,
    but only where sending the request twice is safe. A read (GET, and the
    bulk download) is retried on HTTP 502, 503, 504, timeouts and connection
    errors. A call that creates or changes something — submitting a
    simulation or validation, minting or revoking a key — is retried only on
    503 or when the connection never opened, because a 502, 504 or read
    timeout may arrive after the API acted. A 429 is retried only when it
    carries ``Retry-After``; the download quota's 429 is raised at once. Any
    other non-2xx response, and a retried status still failing once the
    retries run out, raises :class:`~simudyne.exceptions.PulseAPIError`. A timeout or
    connection failure that outlasts the retries is not wrapped: it surfaces
    as the underlying :class:`requests.Timeout` or
    :class:`requests.ConnectionError`, so catch those alongside
    ``PulseAPIError`` if you need to handle every failure.

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
        seconds, so the default waits 1s, 2s then 4s before giving up; a
        ``Retry-After`` header, when sent, is honoured (capped at 60 s).

    Attributes
    ----------
    profile : ProfileResource
        Account details, usage and download history.
    api_keys : ApiKeysResource
        Create, list and revoke API keys.
    data : DataResource
        The market data catalogue: what exists, what is calibrated,
        and calibrating a day.
    simulation : SimulationResource
        Submit agent-based simulations and retrieve their results.
    validation : ValidationResource
        Score synthetic data against real data.
    fm : FmResource
        Foundation-model generation and its job lifecycle.
    fix : FixResource
        FIX gateway usage.

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
    >>> client.profile.get()["email"]
    'you@example.com'
    """

    DEFAULT_BASE_URL = "https://pulse-api.simudyne.com"
    DEFAULT_TIMEOUT = 30
    RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
    #: Methods safe to send twice. DELETE is left out on purpose: a revoke
    #: that succeeded but whose answer was lost would come back as a 404.
    IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}

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
        from simudyne.resources.fix import FixResource
        from simudyne.resources.fm import FmResource
        from simudyne.resources.simulation import SimulationResource
        from simudyne.resources.validation import ValidationResource

        self.profile = ProfileResource(self)
        self.api_keys = ApiKeysResource(self)
        self.data = DataResource(self)
        self.fix = FixResource(self)
        self.fm = FmResource(self)
        self.simulation = SimulationResource(self)
        self.validation = ValidationResource(self)

    def _request_with_retries(self, method: str, url: str, idempotent=None, **kwargs):
        """Execute a request, retrying only what is safe to send twice.

        A read (GET, or a POST the caller marks ``idempotent=True``, such as
        the bulk download) is retried on 502/503/504, on a timeout and on a
        connection failure. A call that creates or changes something —
        submitting a simulation or validation, minting or revoking a key,
        launching a live session — is retried only when the API cannot have
        acted on it: the connection never opened, or the API answered 503.
        A 502, 504 or read timeout on such a call may arrive after the job
        was queued, and retrying it used to queue a second one.

        A 429 is retried only when it carries ``Retry-After``, as a rate
        limiter's does. The API's own 429 is the free-tier download quota,
        which does not clear in seconds; it is raised at once.
        """
        kwargs.setdefault("timeout", self.timeout)
        if idempotent is None:
            idempotent = method.upper() in self.IDEMPOTENT_METHODS
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)

                if response.ok:
                    return response

                if attempt < self.max_retries and self._should_retry(
                    response, idempotent
                ):
                    time.sleep(self._retry_delay(response, attempt))
                    continue

                raise error_from_response(response)

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < self.max_retries and (
                    idempotent or _never_reached_server(e)
                ):
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise last_exception

    def _should_retry(self, response, idempotent: bool) -> bool:
        status = response.status_code
        if status == 429:
            return "Retry-After" in response.headers
        if status not in self.RETRYABLE_STATUS_CODES:
            return False
        return idempotent or status == 503

    @staticmethod
    def _retry_delay(response, attempt: int) -> float:
        """``Retry-After`` seconds when the server gives them (capped at 60),
        otherwise exponential backoff: 1, 2, 4 s."""
        header = response.headers.get("Retry-After")
        if header is not None:
            try:
                return min(max(float(header), 0.0), 60.0)
            except ValueError:
                pass
        return 2 ** attempt

    def _request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retries(method, url, **kwargs)
        return response.json()
    
    def _request_text(self, method: str, endpoint: str, **kwargs):
        """Like _request, for endpoints that answer text/plain not JSON."""
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retries(method, url, **kwargs)
        return response.text

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