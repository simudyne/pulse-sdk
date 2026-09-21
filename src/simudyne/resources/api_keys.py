class ApiKeysResource:
    def __init__(self, client):
        self._client = client

    def create(self, name: str):
        """Mint a new API key.

        The only call that ever returns the key material. It is shown once —
        store it before the call returns, or mint another.

        Parameters
        ----------
        name : str
            A label for the key. Name it by purpose ("notebook",
            "production", "CI pipeline") so you know which to revoke if one
            is compromised.

        Returns
        -------
        dict
            api_key : str
                The key material, shown exactly once.
            api_key_id : str
                The handle to pass to :meth:`revoke`.
            warning : str
                A reminder that the key will not be shown again.

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
        and not enough to reconstruct one.

        Returns
        -------
        list of dict
            One entry per key, each with:

            - api_key_id (str): the handle to pass to :meth:`revoke`
            - key_prefix (str): first 12 characters, e.g. "pk_live_ab12"
            - name (str): the label you gave it
            - is_active (bool): False once revoked
            - created_at (str): when it was created
            - last_used_at (str or None): None until the key is first used
            - expires_at (str or None): None for keys that do not expire

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
            The revocation result.

        Examples
        --------
        >>> new_key = client.api_keys.create(name="Training script")
        >>> client.api_keys.revoke(key_id=new_key["api_key_id"])
        """
        return self._client._request("DELETE", f"/api-keys/{key_id}")
