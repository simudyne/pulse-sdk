"""Tests for the wrappers added to close the gap against pulse-api-pod.

Each of these existed as an endpoint the SDK could not reach, so the point of
the test is that the SDK now targets the right path with the right shape --
including the two that do not return JSON or do not send JSON.
"""

import json

import pytest

from simudyne.resources.data import AVAILABLE_SYMBOLS_PATH, DataResource
from simudyne.resources.simulation import JOBS_PATH, SimulationResource
from simudyne.resources.validation import UPLOAD_PATH, ValidationResource


class FakeClient:
    base_url = "https://api.example.test"

    def __init__(self, text="", json_body=None):
        self.calls = []
        self._text = text
        self._json = json_body or {}

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._json

    def _request_text(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._text

    def _request_with_retries(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))

        class _Resp:
            @staticmethod
            def json():
                return {"job_id": "v1", "status": "pending", "message": "ok"}

        return _Resp()

    @property
    def last(self):
        return self.calls[-1]


class TestJobLogs:
    def test_returns_text_not_json(self):
        client = FakeClient(text="engine boot\nsim 0000 complete\n")
        res = SimulationResource(client)
        out = res.get_job_logs("job-1")
        # text/plain endpoint: _request would raise on .json(), so the resource
        # must route through _request_text
        assert isinstance(out, str)
        assert "sim 0000 complete" in out
        assert client.last[:2] == ("GET", f"{JOBS_PATH}/job-1/logs")


class TestGetJobsLimit:
    def test_limit_is_omitted_by_default(self):
        client = FakeClient()
        SimulationResource(client).get_jobs()
        assert client.last[2]["params"] is None

    def test_limit_is_forwarded(self):
        client = FakeClient()
        SimulationResource(client).get_jobs(limit=250)
        assert client.last[2]["params"] == {"limit": 250}


class TestSymbolSearch:
    def test_q_is_sent_and_is_separate_from_symbol(self):
        client = FakeClient(json_body=[])
        DataResource(client).get_available_symbols(q="tenc")
        method, path, kwargs = client.last
        assert (method, path) == ("GET", AVAILABLE_SYMBOLS_PATH)
        assert kwargs["params"] == {"q": "tenc"}

    def test_no_filters_sends_no_params(self):
        client = FakeClient(json_body=[])
        DataResource(client).get_available_symbols()
        assert client.last[2]["params"] is None


class TestValidationUpload:
    def _files(self, tmp_path, n):
        paths = []
        for i in range(n):
            p = tmp_path / f"sim_{i:04d}.parquet"
            p.write_bytes(b"PAR1fake")
            paths.append(p)
        return paths

    def test_posts_multipart_with_config_as_json_string(self, tmp_path):
        client = FakeClient(json_body={"job_id": "v1"})
        res = ValidationResource(client)
        out = res.run(
            symbol="700.HK", date="2025-09-02",
            provider="omd", exchange="hkex_securities",
            sim_files=self._files(tmp_path, 2),
        )
        method, url, kwargs = client.last
        assert method == "POST" and url.endswith(UPLOAD_PATH)
        assert len(kwargs["files"]) == 2
        assert all(f[0] == "sim_files" for f in kwargs["files"])
        # multipart form fields must be strings, and config a JSON string
        data = kwargs["data"]
        assert data["ticksize"] == "1.0"
        assert "run_fid" not in json.loads(data["config"])
        assert out["job_id"] == "v1"

    def test_tri_state_flags_are_omitted_from_the_config_string(self, tmp_path):
        client = FakeClient(json_body={"job_id": "v1"})
        ValidationResource(client).run(
            symbol="700.HK", date="2025-09-02",
            provider="omd", exchange="hkex_securities",
            sim_files=self._files(tmp_path, 1),
        )
        config = json.loads(client.last[2]["data"]["config"])
        for flag in ("run_metrics", "run_impact", "run_stylised_facts",
                     "plot_data", "run_fid", "statistical", "fid", "mind"):
            assert flag not in config

    def test_accepts_in_memory_pairs(self, tmp_path):
        client = FakeClient(json_body={"job_id": "v1"})
        ValidationResource(client).run(
            symbol="700.HK", date="2025-09-02",
            provider="omd", exchange="hkex_securities",
            sim_files=[("sim_0000.parquet", b"PAR1fake")],
        )
        name, content, mime = client.last[2]["files"][0][1]
        assert name == "sim_0000.parquet" and content == b"PAR1fake"

    def test_rejects_empty_and_oversized_batches(self, tmp_path):
        res = ValidationResource(FakeClient())
        common = dict(symbol="700.HK", date="2025-09-02",
                      provider="omd", exchange="hkex_securities")
        with pytest.raises(ValueError, match="must not be empty"):
            res.run(sim_files=[], **common)
        with pytest.raises(ValueError, match="25"):
            res.run(sim_files=self._files(tmp_path, 26), **common)
