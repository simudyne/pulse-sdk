AVAILABLE_PATH = "/simulation/data/available"


class DataResource:
    def __init__(self, client):
        self._client = client

    def get_available(self):
        """Return all symbols and dates available from symbol_config.

        Returns a flat list of records — one entry per symbol/date combination —
        with full metadata from the symbol_config table.

        Returns:
            list[dict]: Each dict contains:
                - symbol_id (str): Unique symbol identifier (e.g. "700.HK:2025-09-01")
                - name (str): Ticker symbol (e.g. "700.HK")
                - symbol_name (str): Full instrument name (e.g. "TENCENT")
                - date (str): Trading date in YYYY-MM-DD format
                - exchange (str): Exchange code (e.g. "HKEX")
                - instrument_type (str): Instrument classification
                - tick_size (float): Minimum price increment
                - lot_size (int): Minimum lot size
                - currency (str): Trading currency
                - stage (str): Processing pipeline stage
                - status (str): Data status (e.g. "complete", "processing", "error")
                - error_message (str | None): Error detail if status is "error"
                - number_of_msgs (int): Total message count for this session
                - volume_traded (float): Total volume traded
                - reference_price (float): Reference/closing price
                - timestamp (str): Last updated timestamp

        Example:
            >>> catalog = client.data.get_available()
            >>> # Filter to completed sessions only
            >>> complete = [r for r in catalog if r["status"] == "complete"]
            >>> print(f"{len(complete)} sessions available")

            >>> # Group by ticker
            >>> from collections import defaultdict
            >>> by_symbol = defaultdict(list)
            >>> for row in complete:
            ...     by_symbol[row["name"]].append(row["date"])
            >>> print(by_symbol)
        """
        return self._client._request("GET", AVAILABLE_PATH)
