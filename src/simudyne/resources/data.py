SYMBOLS_PATH = "/data/symbols"
ORDERS_PATH = "/data/orders"
TRADES_PATH = "/data/trades"
L1_PATH = "/data/L1"
L2_PATH = "/data/L2"


class DataResource:
    def __init__(self, client):
        self._client = client

    def get_symbols(self, year=None):
        params = {}
        if year:
            params["year"] = year
        return self._client._request("GET", SYMBOLS_PATH, params=params)

    def get_orders(self, sym, datetime_start, datetime_end):
        params = {"sym": sym, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", ORDERS_PATH, params=params)

    def get_trades(self, sym, datetime_start, datetime_end):
        params = {"sym": sym, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", TRADES_PATH, params=params)

    def get_L1(self, sym, datetime_start, datetime_end):
        params = {"sym": sym, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", L1_PATH, params=params)

    def get_L2(self, sym, datetime_start, datetime_end, columns=None):
        params = {"sym": sym, "datetime_start": datetime_start, "datetime_end": datetime_end}
        if columns:
            params["columns"] = columns
        return self._client._request_csv("GET", L2_PATH, params=params)
