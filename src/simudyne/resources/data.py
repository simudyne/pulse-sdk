AVAILABLE_PATH = "/data/available"


class DataResource:
    def __init__(self, client):
        self._client = client

    def get_available(self):
        """Return all symbols and dates available from symbol_config.

        Returns a list of DataCatalogEntry dicts:
            [{"symbol": "700.HK", "exchange": "HKEX", "dates": ["2025-09-01", ...]}]
        """
        return self._client._request("GET", AVAILABLE_PATH)
