import os
import requests
import io
import polars as pl
from tqdm import tqdm
import tempfile
import math




class PulseABM:
    DEFAULT_BASE_URL = "https://simudyne-api-api-pod-dev.apps.c1h9x4c3s0q9y4u.4bmp.p2.openshiftapps.com"

    def __init__(self, api_key: str = None, base_url: str = None):
        
        self.api_key = api_key or os.getenv("SIMUDYNE_API_KEY")
        if not self.api_key:
            raise ValueError("SIMUDYNE_API_KEY is not set -> pass api_key or set SIMUDYNE_API_KEY in environment")
        self.base_url = base_url or os.getenv("SIMUDYNE_BASE_URL", self.DEFAULT_BASE_URL)
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.api_key})

        from simudyne.resources.profile import ProfileResource
        from simudyne.resources.api_keys import ApiKeysResource
        from simudyne.resources.data import DataResource
        from simudyne.resources.historical import HistoricalResource

        self.profile = ProfileResource(self)
        self.api_keys = ApiKeysResource(self)
        self.data = DataResource(self)
        self.historical = HistoricalResource(self)

    def _request(self, method:str,endpoint:str, **kwargs):
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, **kwargs)
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise Exception(f"API Error ({response.status_code}): {detail}")
        return response.json()
    
    def _request_csv(self, method, endpoint, **kwargs):
        PAGE_SIZE = 100000
        params = kwargs.get("params", {})
        
        params["limit"] = PAGE_SIZE
        params["offset"] = 0
        kwargs["params"] = params
        
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, **kwargs)
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise Exception(f"API Error ({response.status_code}): {detail}")
        
        total_rows = int(response.headers.get("X-Total-Rows", 0))
        total_pages = math.ceil(total_rows / PAGE_SIZE) if total_rows > 0 else 1
        
        frames = []
        df = pl.read_csv(response.text.encode(), infer_schema_length=10000)
        frames.append(df)
        schema = df.schema
        
        if total_pages > 1:
            with tqdm(total=total_pages, initial=1, unit="page", desc=f"Downloading ({total_rows:,} rows)") as pbar:
                for page in range(1, total_pages):
                    params["offset"] = page * PAGE_SIZE
                    kwargs["params"] = params
                    response = self.session.request(method, url, **kwargs)
                    if not response.ok:
                        break
                    df = pl.read_csv(response.text.encode(), schema_overrides=schema, infer_schema_length=10000)
                    if df.is_empty():
                        break
                    frames.append(df)
                    pbar.update(1)
        
        result = pl.concat(frames) if len(frames) > 1 else frames[0]
        print(f"Done: {result.shape[0]:,} rows, {result.shape[1]} columns")
        return result