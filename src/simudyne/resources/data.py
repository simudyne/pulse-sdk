AVAILABLE_SYMBOLS_PATH = "/data/available-symbols"


class DataResource:
    """Browse the catalog of calibrated instruments you can simulate.

    Reached as ``client.data``. Every simulation is pinned to a symbol that has
    already been calibrated, so this is the resource that tells you which
    ``provider`` / ``exchange`` / ``symbol`` / ``cal_date`` combinations exist.

    Examples
    --------
    >>> catalog = client.data.get_available_symbols(exchange="hkex_securities")
    >>> for instrument in catalog[:3]:
    ...     dates = instrument["available_dates"]
    ...     print(instrument["symbol"], dates[:2])
    """

    def __init__(self, client):
        self._client = client

    def get_available_symbols(
        self,
        symbol: str | None = None,
        exchange: str | None = None,
        provider: str | None = None,
        date: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ):
        """List calibrated instruments and the dates available for each.

        All arguments are optional filters; with none passed the whole catalog
        comes back, as before.

        Parameters
        ----------
        symbol : str, optional
            Exact symbol, e.g. "700.HK".
        exchange : str, optional
            Exchange protocol, e.g. "hkex_securities".
        provider : str, optional
            Data provider, e.g. "omd" or "bmll".
        date : str, optional
            Calibration date "YYYY-MM-DD". Keeps only instruments
            calibrated on that date, and narrows each instrument's
            available_dates to it.
        q : str, optional
            Case-insensitive substring match over ticker and company name.
        limit : int, optional
            Max instruments to return.
        offset : int, optional
            Instruments to skip (for paging alongside limit).

        Returns
        -------
        list of dict
            One entry per instrument, each with:

            - symbol (str): ticker, e.g. "700.HK"
            - exchange (str): exchange protocol, e.g. "hkex_securities"
            - provider (str): data provider, e.g. "omd"
            - available_dates (list of str): calibration dates, "YYYY-MM-DD",
              any of which is a valid ``cal_date`` for
              :meth:`~simudyne.resources.simulation.SimulationResource.run`

        Raises
        ------
        PulseAPIError
            If a filter is malformed — most often ``date`` not in
            ``YYYY-MM-DD`` form.

        Examples
        --------
        The whole catalog:

        >>> everything = client.data.get_available_symbols()
        >>> len(everything)
        412

        One instrument, to see which dates it can be run for:

        >>> hits = client.data.get_available_symbols(symbol="700.HK")
        >>> first = hits[0]
        >>> print(first["available_dates"])
        ['2025-09-01', '2025-09-02', '2025-09-03']

        Free-text search over ticker and company name, paged:

        >>> page = client.data.get_available_symbols(q="tencent", limit=10)

        Everything calibrated on one date, which is the usual way to pick a
        date that is valid across several instruments:

        >>> on_date = client.data.get_available_symbols(date="2025-09-01")
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
        return self._client._request("GET", AVAILABLE_SYMBOLS_PATH, params=params or None)
