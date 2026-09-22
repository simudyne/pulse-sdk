class ProfileResource:
    """Your account record, request usage and download allowance.

    Reached as ``client.profile``. All three calls are read-only, cheap, and
    available on every tier — :meth:`get` is the usual first call when
    diagnosing an unexpected 403, since ``tier`` is what gates the API.

    Examples
    --------
    >>> me = client.profile.get()
    >>> print(me["email"], me["tier"])
    >>> print(client.profile.downloads()["remaining"], "downloads left")
    """

    def __init__(self, client):
        self._client = client

    def get(self):
        """Return your account record.

        The cheapest way to confirm a key works and to find out which tier it
        is on — worth calling first when a 403 surprises you.

        Returns
        -------
        dict
            user_id : str
                Your account id. Also your FIX CompID, where FIX is enabled.
            email : str
                The address the account was created with.
            name : str
                Display name.
            organization : str
                Organisation, empty string if never set.
            is_admin : bool
                Administrative flag governing user administration, not
                simulator access. It is not a tier bypass: an admin flag on a
                free-tier key still cannot run a simulation. When a call
                returns 403, read ``tier``, not this.
            tier : {"free", "pro", "demo"}
                What gates every endpoint.
            download_limit : int
                New simulation groups per rolling 24 hours. Only enforced on
                the free tier.

        Raises
        ------
        PulseAPIError
            If the key is invalid, revoked or expired — status 401.

        Examples
        --------
        >>> me = client.profile.get()
        >>> print(f"{me['email']} — tier {me['tier']}")

        Check tier before attempting a gated call:

        >>> if client.profile.get()["tier"] == "free":
        ...     print("Simulation requires pro")
        """
        return self._client._request("GET", "/profile")

    def usage(self):
        """Return your request count for the current calendar month.

        Resets on the 1st, and counts *requests* rather than simulations —
        one ``run()`` of 100 Monte Carlo runs is a single request here.

        Returns
        -------
        dict
            user_id : str
                Your account id.
            month : str
                The calendar month being reported, "YYYY-MM".
            total_requests : int
                Requests so far this month.
            by_endpoint : dict
                Request count keyed by endpoint path. The keys are the
                concrete paths that were called, so a job-scoped endpoint
                appears once per job id rather than as a template — aggregate
                by prefix if you want per-endpoint totals.

        Raises
        ------
        PulseAPIError
            If the key is invalid, revoked or expired — status 401.

        Examples
        --------
        >>> usage = client.profile.usage()
        >>> print(f"{usage['month']}: {usage['total_requests']} requests")

        Aggregate the per-path counts back into per-endpoint totals:

        >>> from collections import Counter
        >>> totals = Counter()
        >>> for path, count in usage["by_endpoint"].items():
        ...     totals[path.split("/")[1]] += count
        """
        return self._client._request("GET", "/profile/usage")

    def downloads(self):
        """Return the free-tier download allowance for the current window.

        The unit is a simulation group — every Monte Carlo run of one
        symbol/date/scenario — not a call, a run, or a file. Membership is
        permanent: a group you have downloaded before is free to re-fetch
        forever, in any run or file format.

        Returns
        -------
        dict
            limit : int or None
                Groups per window. None on the pro and demo tiers, meaning
                unlimited.
            used : int
                New groups added in the current window.
            remaining : int or None
                ``limit`` minus ``used``, floored at 0. None when unlimited.
            window_hours : int
                Length of the rolling window, 24.
            downloaded_groups : list of str or None
                Every group you have ever downloaded. None when unlimited.
            downloaded_group_details : list of dict or None
                The same groups, each with a ``downloaded_at`` timestamp.

        Notes
        -----
        A request that would exceed the allowance returns HTTP 429 without
        charging anything, so a partial download never silently eats quota.

        Raises
        ------
        PulseAPIError
            If the key is invalid, revoked or expired — status 401.

        Examples
        --------
        >>> quota = client.profile.downloads()
        >>> print(f"{quota['used']}/{quota['limit']} used, {quota['remaining']} left")

        ``limit`` is None on pro and demo, so guard before comparing:

        >>> if quota["remaining"] is not None and quota["remaining"] == 0:
        ...     print("Allowance exhausted; previously fetched groups are still free")
        """
        return self._client._request("GET", "/profile/downloads")
