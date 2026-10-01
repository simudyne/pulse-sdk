"""Payload tests for the 0.8.0 surface: validation.run, the fm and fix
resources, and simulation.get_job_logs / run_lrm.

No network — same recorder pattern as test_validation.py. These pin the wire
contract the docs describe: field names, which flags are omitted when unset,
and the client-side sim_files limit that must fail before any bytes move.
"""

import json

import pytest

from simudyne.resources.data import DataResource
from simudyne.resources.fix import FixResource
from simudyne.resources.fm import FmResource
from simudyne.resources.simulation import SimulationResource
from simudyne.resources.validation import ValidationResource


class FakeClient:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0) if self._responses else {}


class TestRunUpload:
    def test_rejects_empty_before_any_request(self):
        client = FakeClient()
        with pytest.raises(ValueError, match="empty"):
            ValidationResource(client).run(
                "700.HK", "2025-09-01", "omd", "hkex_securities", sim_files=[]
            )
        assert client.calls == []

    def test_rejects_more_than_25_before_any_request(self):
        client = FakeClient()
        files = [(f"sim_{i}.parquet", b"x") for i in range(26)]
        with pytest.raises(ValueError, match="25"):
            ValidationResource(client).run(
                "700.HK", "2025-09-01", "omd", "hkex_securities", sim_files=files
            )
        assert client.calls == []

    def test_multipart_payload_shape(self):
        client = FakeClient([{"job_id": "v1", "status": "pending"}])
        ValidationResource(client).run(
            "700.HK", "2025-09-01", "omd", "hkex_securities",
            sim_files=[("sim_0000.parquet", b"PARQ")],
            statistical=False,
        )
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/validation/run/upload")
        data = kwargs["data"]
        assert data["provider"] == "omd" and data["exchange"] == "hkex_securities"
        config = json.loads(data["config"])
        # explicit False sent; unset area flags omitted (tier default)
        assert config["statistical"] is False
        for flag in ("impact", "stylised_facts", "fid", "mind",
                     "run_metrics", "plot_data"):
            assert flag not in config
        [(field, (filename, content, mime))] = kwargs["files"]
        assert field == "sim_files" and filename == "sim_0000.parquet"
        assert content == b"PARQ" and mime == "application/octet-stream"

    def test_reads_paths_from_disk(self, tmp_path):
        p = tmp_path / "sim_0001.parquet"
        p.write_bytes(b"BYTES")
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            "700.HK", "2025-09-01", "omd", "hkex_securities", sim_files=[p]
        )
        [(_, (filename, content, _))] = client.calls[0][2]["files"]
        assert filename == "sim_0001.parquet" and content == b"BYTES"


class TestFmResource:
    """Only the registry and the live session live on this resource now —
    running an FM is client.simulation.run(engine="fm")."""

    def test_models_path(self):
        client = FakeClient([{}])
        FmResource(client).models()
        assert client.calls[0][:2] == ("GET", "/fm/models")

    def test_live_path_and_omitted_knobs(self):
        client = FakeClient([{}])
        FmResource(client).live("tradefm-hkex", horizon=5000)
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/fm/live")
        body = kwargs["json"]
        assert body["model_id"] == "tradefm-hkex" and body["horizon"] == 5000
        # `prompt` is gone from the whole surface: the orchestrator builds
        # every prompt itself and always discarded a caller-supplied one.
        assert "prompt" not in body
        assert "model_args" not in body

    def test_running_is_not_on_this_resource(self):
        # The merge is the point: a caller who reaches for client.fm.run gets
        # an AttributeError pointing them at client.simulation.run, rather than
        # a second way to submit a job.
        for gone in ("run", "job_status", "job_logs", "available_data"):
            assert not hasattr(FmResource(FakeClient([])), gone)


class TestDataResource:
    def test_available_data_omits_unset_filters(self):
        client = FakeClient([{}])
        DataResource(client).available_data(model_id="tradefm-hkex", limit=5)
        _, path, kwargs = client.calls[0]
        assert path == "/data/available-data"
        assert kwargs["params"] == {"model_id": "tradefm-hkex", "limit": 5}

    def test_calibration_state_is_opt_in(self):
        client = FakeClient([{}, {}])
        DataResource(client).available_data(symbol="700")
        DataResource(client).available_data(symbol="700", include_calibration_state=True)
        assert "include_calibration_state" not in client.calls[0][2]["params"]
        assert client.calls[1][2]["params"]["include_calibration_state"] is True

    def test_calibrated_data_path(self):
        client = FakeClient([{}])
        DataResource(client).calibrated_data(date="2025-09-01")
        _, path, kwargs = client.calls[0]
        assert path == "/data/calibrated-data"
        assert kwargs["params"] == {"date": "2025-09-01"}

    def test_calibrate_moved_under_data(self):
        client = FakeClient([{}])
        DataResource(client).calibrate("700.HK", "2025-09-01", "omd", "hkex_securities")
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/data/calibrate")
        assert kwargs["json"]["optimize_adj_params"] is True


class TestRunEngines:
    """One endpoint, two engines. The SDK sends only the fields belonging to
    the engine asked for, because the API rejects the other engine's fields
    rather than ignoring them."""

    MARKET = dict(symbol="700", cal_date="2025-09-02",
                  provider="bmll", exchange="hkex_securities")

    def _body(self, **kwargs):
        client = FakeClient([{}])
        SimulationResource(client).run(**kwargs)
        method, path, call_kwargs = client.calls[0]
        assert (method, path) == ("POST", "/simulation/run")
        return call_kwargs["json"]

    def test_abm_is_the_default_engine(self):
        assert self._body(**self.MARKET)["engine"] == "abm"

    def test_abm_sends_no_model_fields(self):
        body = self._body(scenario="flash_crash", **self.MARKET)
        assert body["scenario"] == "flash_crash"
        for absent in ("model_id", "duration_minutes", "horizon", "device", "model_args"):
            assert absent not in body

    def test_fm_sends_no_scenario(self):
        body = self._body(engine="fm", model_id="m", duration_minutes=30, **self.MARKET)
        assert body["model_id"] == "m" and body["duration_minutes"] == 30
        assert "scenario" not in body and "scenario_params" not in body

    def test_unset_n_runs_is_left_to_the_api(self):
        # The default differs per engine (5 and 1), so the SDK sends nothing
        # rather than keeping a second copy of that rule.
        assert "n_runs" not in self._body(**self.MARKET)

    def test_testdata_run_sends_no_market_fields(self):
        body = self._body(engine="fm", model_id="m")
        for absent in ("symbol", "cal_date", "provider", "exchange"):
            assert absent not in body


class TestFixResource:
    def test_usage_path(self):
        client = FakeClient([{}])
        FixResource(client).usage()
        assert client.calls[0][:2] == ("GET", "/fix/usage")


class TestSimulationAdditions:
    def test_run_lrm_payload(self):
        client = FakeClient([{}])
        SimulationResource(client).run_lrm(
            "700", "2025-09-02", "omd", "hkex_securities",
            order_sizes=[10, 50, 100], side="buy",
        )
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/simulation/lrm/run")
        body = kwargs["json"]
        assert body["order_sizes"] == [10, 50, 100]
        assert body["strategy"] == "vwap" and body["side"] == "buy"

    def test_get_job_logs_returns_plain_text(self):
        class TextClient(FakeClient):
            base_url = "https://api.test"

            def _request_with_retries(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))

                class R:
                    text = "engine log line"

                return R()

        client = TextClient()
        out = SimulationResource(client).get_job_logs("job-1")
        assert out == "engine log line"
        assert client.calls[0][1].endswith("/simulation/jobs/job-1/logs")
