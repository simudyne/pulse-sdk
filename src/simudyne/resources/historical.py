class HistoricalResource:
    def __init__(self, client):
        self._client = client

    def get_symbols(self, year=None, dataset=None):
        params = {}
        if year:
            params["year"] = year
        if dataset:
            params["dataset"] = dataset
        return self._client._request("GET", "/historical/symbols", params=params)

    def get_order_book(self, ric, datetime_start, datetime_end):
        params = {"ric": ric, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", "/historical/order_book", params=params)

    def get_L1(self, ric, datetime_start, datetime_end):
        params = {"ric": ric, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", "/historical/L1", params=params)

    def get_L2(self, ric, datetime_start, datetime_end, columns=None):
        params = {"ric": ric, "datetime_start": datetime_start, "datetime_end": datetime_end}
        if columns:
            params["columns"] = columns
        return self._client._request_csv("GET", "/historical/L2", params=params)

    def get_orders_equities(self, ric, datetime_start, datetime_end):
        params = {"ric": ric, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", "/historical/orders_equities", params=params)

    def get_orders_derivatives(self, ric, datetime_start, datetime_end):
        params = {"ric": ric, "datetime_start": datetime_start, "datetime_end": datetime_end}
        return self._client._request_csv("GET", "/historical/orders_derivatives", params=params)