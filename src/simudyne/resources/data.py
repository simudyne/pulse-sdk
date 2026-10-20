"""Market data: what exists, what the agent-based model can simulate, and the
one action that moves a symbol-day from the first to the second.

Reached as ``client.data``. The three calls are one story:

    available_data()    every symbol-day in the registry
    calibrate()         calibrate one of them
    calibrated_data()   the ones the ABM can now simulate

A foundation-model run is prompted from anything in ``available_data``; an
agent-based run needs the day to appear in ``calibrated_data`` first.

``available_data`` and ``calibrated_data`` take the same filters and return the
same rows; the only difference is that the second keeps calibrated days only.
"""

AVAILABLE_DATA_PATH = "/data/available-data"
CALIBRATED_DATA_PATH = "/data/calibrated-data"
CALIBRATE_PATH = "/data/calibrate"

_FILTERS_DOC = """
        symbol : str, optional
            Exact symbol, e.g. "700" or "TSCO".
        q : str, optional
            Case-insensitive substring match over the symbol (and, for
            calibrated days, the company name).
        provider : str, optional
            Data provider, e.g. "omd" or "bmll".
        exchange : str, optional
            Exchange protocol, e.g. "lse" or "hkex_securities".
        date : str, optional
            One trading date "YYYY-MM-DD". Keeps only instruments with that
            day, and returns only that day. Not with ``date_from``/``date_to``.
        date_from, date_to : str, optional
            A date range "YYYY-MM-DD", inclusive.
        calibration_status : {"calibrated", "failed", "in_progress"}, optional
            Days whose LATEST calibration record says this. ``failed`` covers a
            failure at any stage; the reason is in ``calibration_error``.
        min_trades, max_trades, min_messages, max_messages, min_volume,
        max_volume, min_spread_ticks, max_spread_ticks : number, optional
            Bounds on a scanned day's measured stats. Demo tier.
        tick_size, lot_size : float, optional
            Scanned days with exactly this tick or lot size. Demo tier.
        currency, instrument_type : str, optional
            Scanned days in this currency (e.g. "GBp") or of this type
            (e.g. "equity"). Demo tier.
        calibratable : bool, optional
            Scanned days that can (True) or cannot (False) be calibrated: a
            day needs at least one trade and fewer than 10,000,000 messages.
            Demo tier.
        scanned_only : bool, default False
            Only days the catalog has scanned. Demo tier.
        include_stats : bool, default False
            Add each scanned day's measured ``stats``. Demo tier; ``None`` on
            every other tier.
"""

_ROWS_DOC = """
            ``{total, limit, offset, symbols}``, paged by instrument
            (symbol, provider, exchange) so an instrument's dates are never
            truncated; ``total`` is the match count before paging. Each
            instrument has:

            - symbol, provider, exchange
            - company_name, instrument_type, currency, tick_size, lot_size
            - date_count, calibrated_count, first_date, last_date
            - avg_number_of_msgs, avg_volume_traded: over its calibrated days
            - dates (list of dict), one per day:

              - date (str), calibrated (bool)
              - calibration_status: "calibrated", "failed", "in_progress", or
                None if the day was never put through calibration, from the
                day's LATEST calibration record
              - calibration_stage, calibration_error, calibration_updated_at,
                pulse_version, number_of_msgs, volume_traded, reference_price
              - scanned, calibratable, not_calibratable_reason, event_counts,
                stats: figures from the vendor data, demo tier only (None on
                every other tier)

            Filtering on a demo-tier field from another tier raises 403 rather
            than returning an unfiltered answer.
"""


#: On/off flags whose False is the server's default, so False is not sent.
#: (calibratable is not one: False asks for the days that CANNOT be calibrated.)
_DEFAULT_OFF_FLAGS = ("scanned_only", "include_stats")


def _day_params(**filters) -> dict | None:
    """Query parameters for either catalog call, without unset filters."""
    params = {
        k: v for k, v in filters.items()
        if v is not None and not (k in _DEFAULT_OFF_FLAGS and v is False)
    }
    return params or None


class DataResource:
    """Browse the market data catalogue and calibrate days in it.

    Reached as ``client.data``. Every simulation is pinned to a symbol-day, so
    this is the resource that tells you which ``provider`` / ``exchange`` /
    ``symbol`` / ``cal_date`` combinations exist and which are ready to run.

    Examples
    --------
    >>> catalog = client.data.calibrated_data(exchange="hkex_securities")
    >>> for instrument in catalog["symbols"][:3]:
    ...     print(instrument["symbol"], [d["date"] for d in instrument["dates"][:2]])
    """

    def __init__(self, client):
        self._client = client

    def available_data(
        self,
        model_id: str | None = None,
        symbol: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        exchange: str | None = None,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        calibration_status: str | None = None,
        min_trades: int | None = None,
        max_trades: int | None = None,
        min_messages: int | None = None,
        max_messages: int | None = None,
        min_volume: float | None = None,
        max_volume: float | None = None,
        min_spread_ticks: float | None = None,
        max_spread_ticks: float | None = None,
        tick_size: float | None = None,
        lot_size: float | None = None,
        currency: str | None = None,
        instrument_type: str | None = None,
        calibratable: bool | None = None,
        scanned_only: bool = False,
        include_stats: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Every symbol-day in the data registry: what EXISTS, with its
        calibration state.

        The raw-data catalogue, so it answers both "what can a foundation model
        be prompted with?" and "what could I calibrate?". :meth:`calibrated_data`
        takes the same filters and returns the same rows, restricted to
        calibrated days.

        The catalogue holds the whole vendor universe (~15k symbols) and is
        never returned whole, so narrow it with filters and page through it
        with ``limit`` and ``offset``.

        Parameters
        ----------
        model_id : str, optional
            A model from :meth:`~simudyne.resources.fm.FmResource.models`.
            Keeps only the markets that model's ``supported_data`` declares, so
            what comes back is exactly what it will accept at
            :meth:`~simudyne.resources.simulation.SimulationResource.run` with
            ``engine="fm"``. A ``production_name`` (e.g. "flow-hkex-1-100M")
            works too, matched as on ``run``. An unknown model raises (404),
            and a name matching more than one model raises (400).
        {filters}
        limit : int, optional
            Max instruments to return (1-200, default 50).
        offset : int, optional
            Instruments to skip, for paging alongside ``limit``.

        Returns
        -------
        dict
        {rows}

        Raises
        ------
        PulseAPIError
            If the key is not pro or demo tier (403), or filters on a demo-tier
            field from another tier (403); ``model_id`` names a model that is
            not registered (404) or matches more than one (400); a date is not
            ``YYYY-MM-DD``, ``date`` is combined with a range, ``limit`` is
            outside 1-200 or ``offset`` is negative (422); or, with
            ``model_id``, the model registry (pulse-orchestrator) could not be
            reached (502).

        See Also
        --------
        calibrated_data : The subset the agent-based model can simulate.
        calibrate : Move one symbol-day from here to there.

        Examples
        --------
        Search the registry:

        >>> page = client.data.available_data(q="tsc", exchange="lse")
        >>> page["total"]
        3

        What one model can be prompted with, which is the usual pre-run call:

        >>> page = client.data.available_data(model_id="pulse-lob-1", limit=20)
        >>> first = page["symbols"][0]
        >>> first["symbol"], [d["date"] for d in first["dates"][:2]]
        ('AZN', ['2026-06-22', '2026-06-23'])

        Which of a symbol's days are calibrated, and why the others failed:

        >>> entry = client.data.available_data(symbol="700")["symbols"][0]
        >>> entry["date_count"], entry["calibrated_count"]
        (60, 4)
        >>> [(d["date"], d["calibration_error"]) for d in entry["dates"]
        ...  if d["calibration_status"] == "failed"]

        Days that can be calibrated but are not yet (demo tier):

        >>> page = client.data.available_data(
        ...     exchange="lse", date_from="2025-07-01", date_to="2025-07-31",
        ...     calibratable=True,
        ... )
        """
        return self._client._request("GET", AVAILABLE_DATA_PATH, params=_day_params(
            model_id=model_id, symbol=symbol, q=q, provider=provider, exchange=exchange,
            date=date, date_from=date_from, date_to=date_to,
            calibration_status=calibration_status,
            min_trades=min_trades, max_trades=max_trades,
            min_messages=min_messages, max_messages=max_messages,
            min_volume=min_volume, max_volume=max_volume,
            min_spread_ticks=min_spread_ticks, max_spread_ticks=max_spread_ticks,
            tick_size=tick_size, lot_size=lot_size,
            currency=currency, instrument_type=instrument_type,
            calibratable=calibratable, scanned_only=scanned_only,
            include_stats=include_stats, limit=limit, offset=offset,
        ))

    def calibrated_data(
        self,
        symbol: str | None = None,
        exchange: str | None = None,
        provider: str | None = None,
        date: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_trades: int | None = None,
        max_trades: int | None = None,
        min_messages: int | None = None,
        max_messages: int | None = None,
        min_volume: float | None = None,
        max_volume: float | None = None,
        min_spread_ticks: float | None = None,
        max_spread_ticks: float | None = None,
        tick_size: float | None = None,
        lot_size: float | None = None,
        currency: str | None = None,
        instrument_type: str | None = None,
        calibratable: bool | None = None,
        scanned_only: bool = False,
        include_stats: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Symbol-days the agent-based model can simulate: what is CALIBRATED.

        A day is calibrated when its LATEST calibration record is a complete
        model calibration, so a later failed re-run takes it out. Every day
        here is a valid ``symbol`` / ``provider`` / ``exchange`` /
        ``cal_date`` for
        :meth:`~simudyne.resources.simulation.SimulationResource.run` with
        ``engine="abm"``. Same filters and same rows as :meth:`available_data`;
        :meth:`calibrate` is what moves a day from there to here.

        Parameters
        ----------
        {filters}
        limit : int, optional
            Max instruments to return, 1-1000. Omitted, the whole calibrated
            catalogue comes back — it is far smaller than the registry.
        offset : int, optional
            Instruments to skip, for paging alongside ``limit``.

        Returns
        -------
        dict
        {rows}

        Raises
        ------
        PulseAPIError
            If a filter on a demo-tier field comes from another tier (403), or
            a date is not ``YYYY-MM-DD``, ``limit`` is outside 1-1000 or
            ``offset`` is negative (422). Available on every tier.

        See Also
        --------
        available_data : Everything that exists, calibrated or not.

        Examples
        --------
        The whole calibrated catalogue:

        >>> everything = client.data.calibrated_data()
        >>> everything["total"]
        412

        One instrument, to see which dates it can be run for:

        >>> hits = client.data.calibrated_data(symbol="700.HK")
        >>> [d["date"] for d in hits["symbols"][0]["dates"]]
        ['2025-09-01', '2025-09-02', '2025-09-03']

        Everything calibrated on one date, the usual way to pick a date that is
        valid across several instruments:

        >>> on_date = client.data.calibrated_data(date="2025-09-01")

        Free-text search over ticker and company name, paged:

        >>> page = client.data.calibrated_data(q="tencent", limit=10)
        """
        return self._client._request("GET", CALIBRATED_DATA_PATH, params=_day_params(
            symbol=symbol, q=q, provider=provider, exchange=exchange,
            date=date, date_from=date_from, date_to=date_to,
            min_trades=min_trades, max_trades=max_trades,
            min_messages=min_messages, max_messages=max_messages,
            min_volume=min_volume, max_volume=max_volume,
            min_spread_ticks=min_spread_ticks, max_spread_ticks=max_spread_ticks,
            tick_size=tick_size, lot_size=lot_size,
            currency=currency, instrument_type=instrument_type,
            calibratable=calibratable, scanned_only=scanned_only,
            include_stats=include_stats, limit=limit, offset=offset,
        ))

    # The two calls share their filters and row shape, so their docs share the
    # text too. (Docstrings are None under python -OO.)
    for _method in (available_data, calibrated_data):
        if _method.__doc__:
            _method.__doc__ = _method.__doc__.replace(
                "{filters}", _FILTERS_DOC.strip("\n").lstrip()
            ).replace("{rows}", _ROWS_DOC.strip("\n").lstrip())
    del _method

    def calibrate(
        self,
        symbol: str,
        cal_date: str,
        provider: str,
        exchange: str,
        simulations: int = None,
        batch_size: int = None,
        optimize_adj_params: bool = True,
    ):
        """Fit the agent-based model to one symbol-day.

        Calibration is a data operation: its input is a day from
        :meth:`available_data` and its output is an entry in
        :meth:`calibrated_data`. It runs asynchronously — the call returns once
        the job is queued, and the day appears in :meth:`calibrated_data` when
        the pipeline finishes. Demo tier only.

        A symbol is identified by four fields: ``provider``, ``exchange``,
        ``symbol`` and ``cal_date``.

        Parameters
        ----------
        symbol : str
            Trading symbol, e.g. "9999.HK".
        cal_date : str
            Trading day in YYYY-MM-DD format.
        provider : str
            Data provider the symbol is sourced from: "omd" or "bmll".
        exchange : str
            Exchange protocol name, e.g. "hkex_securities".
        simulations : int, optional
            Number of simulations to run during calibration.
        batch_size : int, optional
            Batch size for calibration runs.
        optimize_adj_params : bool, default True
            Whether to optimise adjustment parameters.

        Returns
        -------
        dict
            status : str
                "calibration_queued".
            symbol : str
                The symbol as submitted.
            cal_date : str
                The date as submitted.

            There is no job id. Follow the day in :meth:`available_data`:
            its ``calibration_status`` goes to "calibrated" when the pipeline
            finishes, or to "failed" with the reason in ``calibration_error``.

        Raises
        ------
        PulseAPIError
            If the key is not demo tier (403); ``provider`` or ``exchange`` is
            not a recognised value (422); the day has no market data — a
            weekend, an exchange holiday, a day the vendor did not deliver
            (422); the catalog has scanned the day and it cannot be calibrated,
            e.g. it has no trades (422, with the reason); or the calibration
            service is unreachable (503).

        See Also
        --------
        available_data : Days that exist and could be calibrated.
        calibrated_data : Days already calibrated, where this one lands.
        simudyne.resources.simulation.SimulationResource.run : Simulate a calibrated day.

        Notes
        -----
        Calibration is only needed for a symbol-day that is not already
        calibrated, and it is far slower than running against an existing
        calibration. Check :meth:`calibrated_data` first — most instruments are
        calibrated already.

        Examples
        --------
        >>> job = client.data.calibrate(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ... )
        >>> job["status"]
        'calibration_queued'

        With an explicit budget, and adjustment-parameter optimisation off:

        >>> job = client.data.calibrate(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ...     simulations=500,
        ...     batch_size=50,
        ...     optimize_adj_params=False,
        ... )
        """
        payload: dict = {
            "symbol": symbol,
            "cal_date": cal_date,
            "provider": provider,
            "exchange": exchange,
            "optimize_adj_params": optimize_adj_params,
        }
        if simulations is not None:
            payload["simulations"] = simulations
        if batch_size is not None:
            payload["batch_size"] = batch_size
        return self._client._request("POST", CALIBRATE_PATH, json=payload)
