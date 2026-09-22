"""Market data: what exists, what the agent-based model can simulate, and the
one action that moves a symbol-day from the first to the second.

Reached as ``client.data``. The three calls are one story:

    available_data()    every symbol-day in the registry
    calibrate()         calibrate one of them
    calibrated_data()   the ones the ABM can now simulate

A foundation-model run is prompted from anything in ``available_data``; an
agent-based run needs the day to appear in ``calibrated_data`` first.
"""

AVAILABLE_DATA_PATH = "/data/available-data"
CALIBRATED_DATA_PATH = "/data/calibrated-data"
CALIBRATE_PATH = "/data/calibrate"


class DataResource:
    """Browse the market data catalogue and calibrate days in it.

    Reached as ``client.data``. Every simulation is pinned to a symbol-day, so
    this is the resource that tells you which ``provider`` / ``exchange`` /
    ``symbol`` / ``cal_date`` combinations exist and which are ready to run.

    Examples
    --------
    >>> catalog = client.data.calibrated_data(exchange="hkex_securities")
    >>> for instrument in catalog["symbols"][:3]:
    ...     print(instrument["symbol"], instrument["available_dates"][:2])
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
        include_calibration_state: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Every symbol-day in the data registry: what EXISTS.

        The raw-data catalogue, so it answers both "what can a foundation model
        be prompted with?" and "what could I calibrate?". Its counterpart is
        :meth:`calibrated_data`, which lists only the days the agent-based
        pipeline has already processed.

        Every filter is applied in the database. The catalogue holds the whole
        vendor universe (~15k symbols) and is never returned whole, so page
        through it with ``limit`` and ``offset`` rather than asking for all of
        it.

        Parameters
        ----------
        model_id : str, optional
            A model from :meth:`~simudyne.resources.fm.FmResource.models`.
            Keeps only the markets that model's ``supported_data`` declares, so
            what comes back is exactly what it will accept at
            :meth:`~simudyne.resources.simulation.SimulationResource.run` with
            ``engine="fm"``. An unknown id raises.
        symbol : str, optional
            Exact symbol, e.g. "700" or "TSCO".
        q : str, optional
            Case-insensitive substring match over the symbol.
        provider : str, optional
            Data provider, e.g. "omd" or "bmll". Narrows further within
            ``model_id``'s markets when both are given.
        exchange : str, optional
            Exchange protocol, e.g. "lse" or "hkex_securities".
        date : str, optional
            Trading date "YYYY-MM-DD". Keeps only symbols with data on that
            day, and returns only that day.
        include_calibration_state : bool, default False
            Also return ``calibrated_dates`` and ``calibrated_count`` per
            symbol — which of its days the agent-based model has already
            calibrated. Costs a second query, so it is off by default; it means
            nothing to a foundation model.
        limit : int, optional
            Max symbols to return (1-200, default 50).
        offset : int, optional
            Symbols to skip, for paging alongside ``limit``.

        Returns
        -------
        dict
            ``{total, limit, offset, symbols}``, paged by symbol identity
            rather than by row so a symbol's dates are never truncated.
            ``total`` is the match count before paging. Each symbol has:

            - symbol (str): the ticker, e.g. "700"
            - provider (str), exchange (str): the market it came from
            - dates (list of str): trading days present, "YYYY-MM-DD"
            - calibrated_dates (list of str), calibrated_count (int): only
              with ``include_calibration_state``

            ``dates`` is always a list of strings, with or without calibration
            state, so a caller never branches on the shape of the response.

        Raises
        ------
        PulseAPIError
            If the key is not pro or demo tier (403), ``model_id`` names a
            model that is not registered (404), or ``date`` is not
            ``YYYY-MM-DD`` (422).

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
        >>> first["symbol"], first["dates"][:2]
        ('AZN', ['2026-06-22', '2026-06-23'])

        Which of a symbol's days are already calibrated:

        >>> page = client.data.available_data(
        ...     symbol="700", include_calibration_state=True,
        ... )
        >>> entry = page["symbols"][0]
        >>> len(entry["dates"]), entry["calibrated_count"]
        (60, 4)
        """
        params = {
            k: v for k, v in {
                "model_id": model_id,
                "symbol": symbol,
                "q": q,
                "provider": provider,
                "exchange": exchange,
                "date": date,
                "include_calibration_state": include_calibration_state or None,
                "limit": limit,
                "offset": offset,
            }.items() if v is not None
        }
        return self._client._request("GET", AVAILABLE_DATA_PATH, params=params or None)

    def calibrated_data(
        self,
        symbol: str | None = None,
        exchange: str | None = None,
        provider: str | None = None,
        date: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """Symbol-days the agent-based model can simulate: what is CALIBRATED.

        Every entry is a valid ``symbol`` / ``provider`` / ``exchange`` /
        ``cal_date`` for
        :meth:`~simudyne.resources.simulation.SimulationResource.run` with
        ``engine="abm"``. A day that exists but has never been calibrated
        appears in :meth:`available_data` and not here; :meth:`calibrate` is
        what moves it across.

        Parameters
        ----------
        symbol : str, optional
            Exact symbol, e.g. "700.HK".
        exchange : str, optional
            Exchange protocol, e.g. "hkex_securities".
        provider : str, optional
            Data provider, e.g. "omd" or "bmll".
        date : str, optional
            Calibration date "YYYY-MM-DD". Keeps only instruments calibrated
            on that date, and narrows each one's ``available_dates`` to it.
        q : str, optional
            Case-insensitive substring match over ticker and company name.
        limit : int, optional
            Max instruments to return. Omitted, the whole calibrated catalogue
            comes back — it is far smaller than the registry.
        offset : int, optional
            Instruments to skip, for paging alongside ``limit``.

        Returns
        -------
        dict
            ``{total, limit, offset, symbols}``, the same envelope as
            :meth:`available_data`, paged by instrument. Each entry has:

            - symbol (str): the ticker, e.g. "700.HK"
            - company_name (str or None): the issuer's name where the vendor
              reports one
            - provider (str), exchange (str): the market it came from
            - instrument_type, currency, tick_size, lot_size
            - available_dates (list of dict): one per calibrated day, each with
              ``date``, ``status``, ``stage``, ``number_of_msgs``,
              ``volume_traded`` and ``reference_price``. Any ``date`` here is a
              valid ``cal_date`` to run against
            - avg_number_of_msgs, avg_volume_traded: averaged over the dates
              returned, so a ``date`` filter narrows them too

        Raises
        ------
        PulseAPIError
            If a filter is malformed — most often ``date`` not in
            ``YYYY-MM-DD`` form (422).

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
        >>> [d["date"] for d in hits["symbols"][0]["available_dates"]]
        ['2025-09-01', '2025-09-02', '2025-09-03']

        Everything calibrated on one date, the usual way to pick a date that is
        valid across several instruments:

        >>> on_date = client.data.calibrated_data(date="2025-09-01")

        Free-text search over ticker and company name, paged:

        >>> page = client.data.calibrated_data(q="tencent", limit=10)
        """
        params = {
            k: v for k, v in {
                "symbol": symbol,
                "exchange": exchange,
                "provider": provider,
                "date": date,
                "q": q,
                "limit": limit,
                "offset": offset,
            }.items() if v is not None
        }
        return self._client._request("GET", CALIBRATED_DATA_PATH, params=params or None)

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
        the pipeline finishes.

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
            Calibration job submission result, containing the job identifier
            and its accepted status.

        Raises
        ------
        PulseAPIError
            If the key is not demo tier (403), or there is no raw market data
            for the symbol on ``cal_date`` (400).

        Notes
        -----
        Calibration is only needed for a symbol-day that is not already
        calibrated, and it is far slower than running against an existing
        calibration. Check :meth:`calibrated_data` first — most instruments are
        calibrated already.

        Examples
        --------
        >>> job = client.data.calibrate(
        ...     symbol="9999.HK",
        ...     cal_date="2025-09-01",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ... )

        With an explicit budget, and adjustment-parameter optimisation off:

        >>> job = client.data.calibrate(
        ...     symbol="9999.HK",
        ...     cal_date="2025-09-01",
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
