AVAILABLE_SYMBOLS_PATH = "/data/available-symbols"


class DataResource:
    def __init__(self, client):
        self._client = client

    def get_available_symbols(self):
        return self._client._request("GET", AVAILABLE_SYMBOLS_PATH)
