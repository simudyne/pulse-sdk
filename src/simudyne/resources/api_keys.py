class ApiKeysResource:
    """Create, list and revoke the API keys on your account.

    Reached as ``client.api_keys``. Keys are the only credential the SDK
    accepts, and key material is returned exactly once, by :meth:`create`.

    Examples
    --------
    Mint a key for a job, use it, then revoke it:

    >>> from simudyne import PulseABM
    >>> key = client.api_keys.create(name="Nightly backtest")
    >>> run_client = PulseABM(api_key=key["api_key"])
    >>> client.api_keys.revoke(key_id=key["api_key_id"])
    """

    def __init__(self, client):
        self._client = client

    def create(self, name: str = ""):
        """Mint a new API key.

        The only call that ever returns the key material. It is shown once —
        store it before the call returns, or mint another.

        Parameters
        ----------
        name : str, default ""
            A label for the key. Name it by purpose ("notebook",
            "production", "CI pipeline") so you know which to revoke if one
            is compromised. Left blank, the key is named after the account.

        Returns
        -------
        dict
            api_key : str
                The key material, shown exactly once.
            api_key_id : str
                The handle to pass to :meth:`revoke`.
            key_prefix : str
                The first characters of the key, as :meth:`list` shows it.
            name : str
                The label the key was stored under.
            warning : str
                A reminder that the key will not be shown again.

        Raises
        ------
        PulseAPIError
            If the calling key is invalid, revoked or expired — status 401.
            There is no per-account key limit.

        See Also
        --------
        list : Every active key on the account.
        revoke : Deactivate a key.

        Examples
        --------
        >>> new_key = client.api_keys.create(name="Training script")
        >>> print(new_key["api_key"])  # save this, it won't be shown again
        """
        return self._client._request("POST", "/api-keys", json={"name": name})

    def list(self):
        """List your active API keys and their labels.

        The full key is never returned after creation; only ``key_prefix``,
        the first 12 characters, is stored. That is enough to tell keys apart
        and not enough to reconstruct one. Revoked keys are not listed, and
        at most 100 keys are returned.

        Returns
        -------
        list of dict
            One entry per key, each with:

            - api_key_id (str): the handle to pass to :meth:`revoke`
            - key_prefix (str): first 12 characters, e.g. "pk_live_ab12"
            - name (str): the label you gave it
            - is_active (bool): always True, since revoked keys are omitted
            - created_at (str): when it was created
            - last_used_at (str or None): None until the key is first used
            - expires_at (str or None): None for keys that do not expire

        Raises
        ------
        PulseAPIError
            If the calling key is invalid or has been revoked.

        See Also
        --------
        create : Issue a new key.
        revoke : Deactivate a key.

        Examples
        --------
        >>> for key in client.api_keys.list():
        ...     print(key["name"], key["key_prefix"], key["created_at"])
        """
        return self._client._request("GET", "/api-keys")

    def revoke(self, key_id: str):
        """Invalidate a key immediately.

        Any request still using the key returns HTTP 401 from this point on.

        Parameters
        ----------
        key_id : str
            The ``api_key_id`` from :meth:`list` or :meth:`create` — not the
            key material itself.

        Returns
        -------
        dict
            ``{"message": "API key revoked"}``.

        Raises
        ------
        PulseAPIError
            Status 404 if ``key_id`` does not exist, does not belong to your
            account, or has already been revoked; 401 if the calling key is
            invalid.

        See Also
        --------
        list : Find the key id to revoke.
        create : Issue a replacement key.

        Examples
        --------
        >>> new_key = client.api_keys.create(name="Training script")
        >>> client.api_keys.revoke(key_id=new_key["api_key_id"])

        Revoking the key you are currently authenticating with locks you out
        of the API, so mint the replacement first:

        >>> from simudyne import PulseABM
        >>> old_key_id = client.api_keys.list()[0]["api_key_id"]
        >>> replacement = client.api_keys.create(name="Rotated")
        >>> client = PulseABM(api_key=replacement["api_key"])
        >>> client.api_keys.revoke(key_id=old_key_id)
        """
        return self._client._request("DELETE", f"/api-keys/{key_id}")
