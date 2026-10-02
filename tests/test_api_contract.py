"""The SDK against pulse-api-pod 1.77: what it sends, and how failures read.

No network. Pins the behaviour the API now enforces — engine-specific fields
rejected rather than ignored, scenario_params validated server-side, admin
registry routes, readable 422s — so the SDK can't drift back into silently
dropping a caller's input or printing a list repr as an error.
"""

import io

import polars as pl
import pytest

from simudyne.exceptions import PulseAPIError, describe_detail, error_from_response
from simudyne.resources.api_keys import ApiKeysResource
from simudyne.resources.fm import FmResource
from simudyne.resources.simulation import SimulationResource


class FakeClient:
    base_url = "https://api.test"

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0) if self._responses else {}

    def _request_with_retries(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


MARKET = dict(symbol="700.HK", cal_date="2025-09-02", provider="omd", exchange="hkex_securities")


def _sent(client):
    return client.calls[-1][2]["json"]


class TestRunSendsWhatTheCallerSet:
    def test_plain_abm_run_carries_no_fm_fields(self):
        client = FakeClient()
        SimulationResource(client).run(**MARKET)
        body = _sent(client)
        assert body == {"engine": "abm", "seed": 42, **MARKET}

    def test_plain_fm_run_carries_no_abm_fields(self):
        client = FakeClient()
        SimulationResource(client).run(engine="fm", model_id="flow-hkex-1-100M")
        assert _sent(client) == {"engine": "fm", "seed": 42, "model_id": "flow-hkex-1-100M"}

    def test_fm_field_on_abm_run_is_sent_for_the_api_to_reject(self):
        client = FakeClient()
        SimulationResource(client).run(**MARKET, model_id="x", duration_minutes=30)
        body = _sent(client)
        assert body["model_id"] == "x" and body["duration_minutes"] == 30

    def test_scenario_on_fm_run_is_sent_for_the_api_to_reject(self):
        client = FakeClient()
        SimulationResource(client).run(
            engine="fm", model_id="m", scenario="flash_crash", scenario_params={"impact_multiplier": 2.0}
        )
        body = _sent(client)
        assert body["scenario"] == "flash_crash"
        assert body["scenario_params"] == {"impact_multiplier": 2.0}


class TestLrm:
    def test_start_time_and_scenario_reach_the_api(self):
        client = FakeClient()
        SimulationResource(client).run_lrm(
            **MARKET, order_sizes=[10, 20], start_time="10:30",
            scenario="flash_crash", scenario_params={"impact_multiplier": 2.0},
        )
        body = _sent(client)
        assert body["start_time"] == "10:30"
        assert body["scenario"] == "flash_crash"
        assert body["scenario_params"] == {"impact_multiplier": 2.0}
        assert "side" not in body

    def test_unset_extras_are_omitted(self):
        client = FakeClient()
        SimulationResource(client).run_lrm(**MARKET, order_sizes=[10])
        assert not {"start_time", "scenario", "scenario_params", "side"} & set(_sent(client))


def test_get_jobs_pages_with_offset():
    client = FakeClient()
    SimulationResource(client).get_jobs(limit=20, offset=40)
    method, path, kwargs = client.calls[0]
    assert (method, path) == ("GET", "/simulation/jobs")
    assert kwargs["params"] == {"limit": 20, "offset": 40}


class TestFmRegistry:
    def test_registry(self):
        client = FakeClient()
        FmResource(client).registry()
        assert client.calls[0][:2] == ("GET", "/fm/models/registry")

    def test_register_sends_only_what_was_set(self):
        client = FakeClient()
        FmResource(client).register(
            "flob-adaln-rf-1s", "1.0.14", "img:1.0.14", production_name="flow-hkex-1-100M"
        )
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/fm/models")
        assert kwargs["json"] == {
            "model_id": "flob-adaln-rf-1s", "version": "1.0.14", "image": "img:1.0.14",
            "production_name": "flow-hkex-1-100M", "active": True,
        }

    @pytest.mark.parametrize("action", ["activate", "deactivate"])
    def test_activate_and_deactivate(self, action):
        client = FakeClient()
        getattr(FmResource(client), action)("flob-adaln-rf")
        assert client.calls[0][:2] == ("POST", f"/fm/models/flob-adaln-rf/{action}")


def test_api_key_name_is_optional():
    client = FakeClient()
    ApiKeysResource(client).create()
    assert client.calls[0][2]["json"] == {"name": ""}


class FakeResponse:
    def __init__(self, status, body=None, text="", content=b""):
        self.status_code = status
        self._body = body
        self.text = text
        self.content = content
        self.ok = status < 400

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class TestErrorsReadAsText:
    def test_pydantic_list_becomes_field_lines(self):
        body = {"detail": [
            {"loc": ["body", "scenario_params"], "msg": "Value error, scenario_params.order_size_ratio must be in (0, 1]"},
            {"loc": ["body", "n_runs"], "msg": "Input should be greater than or equal to 1"},
        ]}
        exc = error_from_response(FakeResponse(422, body))
        assert exc.status_code == 422
        assert exc.detail == body["detail"]  # kept exactly as sent
        text = str(exc)
        assert "scenario_params: scenario_params.order_size_ratio must be in (0, 1]" in text
        assert "n_runs: Input should be greater than or equal to 1" in text
        assert "[{" not in text

    def test_model_level_error_has_no_location(self):
        detail = [{"loc": [], "msg": "Value error, model_id belongs to engine='fm', not engine='abm'."}]
        assert describe_detail(detail) == "model_id belongs to engine='fm', not engine='abm'."

    def test_guidance_string_keeps_the_field_errors(self):
        body = {"detail": "provider must be one of ...", "errors": [{"loc": ["body", "provider"], "msg": "bad"}]}
        exc = error_from_response(FakeResponse(422, body))
        assert exc.errors == body["errors"]
        assert "provider must be one of" in str(exc) and "provider: bad" in str(exc)

    def test_nested_upstream_detail(self):
        exc = error_from_response(FakeResponse(400, {"detail": {"detail": "model name is ambiguous"}}))
        assert "model name is ambiguous" in str(exc)

    def test_non_dict_json_body(self):
        exc = error_from_response(FakeResponse(500, ["boom"]))
        assert exc.status_code == 500 and "boom" in str(exc)

    def test_non_json_body(self):
        exc = error_from_response(FakeResponse(502, text="Bad Gateway"))
        assert exc.detail == "Bad Gateway"

    def test_plain_string_detail_unchanged(self):
        exc = PulseAPIError(404, "Job not found")
        assert str(exc) == "API Error (404): Job not found"


def test_raw_downloads_go_through_the_retrying_client():
    buf = io.BytesIO()
    pl.DataFrame({"a": [1]}).write_parquet(buf)
    client = FakeClient([FakeResponse(200, content=buf.getvalue())])
    df = SimulationResource(client).get_sim_data("sim", "mid_price_by_min.parquet")
    assert df["a"].to_list() == [1]
    method, url, _ = client.calls[0]
    assert method == "GET" and url.endswith("/sim/data/mid_price_by_min.parquet")
