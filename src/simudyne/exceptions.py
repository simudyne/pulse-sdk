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
    detail : str, list or dict
        The response body's ``detail`` field, or the raw response text when
        the body is not JSON. A request that fails validation (422) carries a
        list of ``{loc, msg, ...}`` entries; an error passed on from an
        upstream service can be a dict.
    errors : list, optional
        The body's top-level ``errors`` field, when present. On a 422 where
        ``detail`` is a guidance string, the field-level errors are here.

    Attributes
    ----------
    status_code : int
        HTTP status code returned by the API.
    detail : str, list or dict
        The ``detail`` field exactly as the API returned it.
    errors : list or None
        The top-level ``errors`` field, or None.

    The exception's message (``str(exc)``) is always readable text: a list of
    validation errors is rendered as ``field: message`` lines rather than the
    Python repr of the list.

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

    def __init__(self, status_code: int, detail, errors=None):
        self.status_code = status_code
        self.detail = detail
        self.errors = errors
        message = describe_detail(detail)
        if errors and not isinstance(detail, list):
            message = f"{message}\n{describe_detail(errors)}"
        super().__init__(f"API Error ({status_code}): {message}")


def _describe_one(entry) -> str:
    if isinstance(entry, dict) and "msg" in entry:
        loc = [str(p) for p in entry.get("loc") or [] if p != "body"]
        # pydantic prefixes a model-level check with "Value error, ".
        msg = str(entry["msg"]).removeprefix("Value error, ")
        return f"{'.'.join(loc)}: {msg}" if loc else msg
    if isinstance(entry, dict) and "detail" in entry:
        return describe_detail(entry["detail"])
    return str(entry)


def describe_detail(detail) -> str:
    """Render an API ``detail`` (string, validation-error list or dict) as text."""
    if isinstance(detail, list):
        lines = [_describe_one(e) for e in detail]
        return lines[0] if len(lines) == 1 else "\n".join(f"- {line}" for line in lines)
    if isinstance(detail, dict):
        return _describe_one(detail)
    return str(detail)


def error_from_response(response) -> PulseAPIError:
    """Build a PulseAPIError from a failed ``requests`` response."""
    try:
        body = response.json()
    except ValueError:
        return PulseAPIError(response.status_code, response.text)
    if not isinstance(body, dict):
        return PulseAPIError(response.status_code, body)
    errors = body.get("errors")
    return PulseAPIError(
        response.status_code,
        body.get("detail", response.text),
        errors if isinstance(errors, list) else None,
    )
