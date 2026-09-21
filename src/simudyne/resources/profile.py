class ProfileResource:
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

        Examples
        --------
        >>> me = client.profile.get()
        >>> print(f"{me['email']} — tier {me['tier']}")
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

        Examples
        --------
        >>> usage = client.profile.usage()
        >>> print(f"{usage['month']}: {usage['total_requests']} requests")
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

        Examples
        --------
        >>> quota = client.profile.downloads()
        >>> print(f"{quota['used']}/{quota['limit']} used, {quota['remaining']} left")
        """
        return self._client._request("GET", "/profile/downloads")
