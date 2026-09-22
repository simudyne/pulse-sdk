class PulseAPIError(Exception):
    """Raised when the Pulse API returns a non-2xx response.

    Every resource method raises this on API-level failure. Transient statuses
    (429, 502, 503, 504) are retried by the client first, so receiving this
    means the request failed after all retries were exhausted, or failed with a
    status that is not worth retrying.

    Parameters
    ----------
    status_code : int
        HTTP status code returned by the API.
    detail : str
        Message from the response body's ``detail`` field, or the raw response
        text when the body is not JSON.

    Attributes
    ----------
    status_code : int
        HTTP status code returned by the API.
    detail : str
        Human-readable explanation of the failure.

    Examples
    --------
    >>> try:
    ...     client.simulation.get_job_status("does-not-exist")
    ... except PulseAPIError as exc:
    ...     print(exc.status_code, exc.detail)
    404 Job not found

    Retry only on rate limiting, and let anything else surface:

    >>> try:
    ...     client.simulation.run(...)
    ... except PulseAPIError as exc:
    ...     if exc.status_code != 429:
    ...         raise
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error ({status_code}): {detail}")
