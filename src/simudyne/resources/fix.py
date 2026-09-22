"""FIX venue usage: what you have run over a FIX session.

The FIX venue itself is a raw-TCP FIX 4.4 acceptor, not an HTTP API — you reach
it with your own FIX engine, not with this SDK. What lives here is the one
HTTP endpoint a FIX client wants: a record of what it has run.

Runs are written by the venue rather than by the client, because the venue is
what knows the session, the account and the start parameters. Only the shape of
a run is kept -- symbol, date, scenario, speed, horizon. No orders, no
schedules, no fills: that is your strategy, and it is not ours to store.
"""

USAGE_PATH = "/fix/usage"


class FixResource:
    """Usage records for simulations started over the FIX venue.

    Reached as ``client.fix``. The venue itself is raw-TCP FIX 4.4 and is not
    driven from this SDK — you connect to it with your own FIX engine. This
    resource only reads back what the venue recorded.

    Examples
    --------
    >>> usage = client.fix.usage()
    >>> print(usage["total_runs"], "runs,", usage["simulated_seconds"], "s")
    """

    def __init__(self, client):
        self._client = client

    def usage(self, user_id: str = None):
        """Simulations you have started over FIX, and how many times.

        Parameters
        ----------
        user_id : str, optional
            Another account to read, which requires an admin key.
            Omit it for your own usage.

        Returns
        -------
        dict
            Usage summary containing:

            - total_runs (int): FIX sessions recorded
            - simulated_seconds (float): total horizon across those runs
            - by_symbol / by_scenario / by_cal_date (dict): run counts
            - runs (list of dict): one ``{symbol, cal_date, scenario, runs}``
              per distinct combination, most-run first
            - last_run_at (str or None): when the most recent one started,
              None if nothing has been run
            - truncated (bool): True if the history hit the server's cap

        Raises
        ------
        PulseAPIError
            If ``user_id`` is given without an admin key, or names an account
            that does not exist.

        Examples
        --------
        >>> usage = client.fix.usage()
        >>> print(f"{usage['total_runs']} FIX runs")
        >>> runs = usage["runs"]
        >>> for run in runs[:5]:
        ...     print(f"  {run['symbol']} {run['cal_date']} "
        ...           f"{run['scenario']}: {run['runs']}x")

        Read another account, which needs an admin key:

        >>> client.fix.usage(user_id="usr_01H...")
        """
        params = {"user_id": user_id} if user_id else None
        return self._client._request("GET", USAGE_PATH, params=params)
