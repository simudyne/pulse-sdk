"""Tests for the foundation-model resource's requests.

No network: the client's _request is a recorder, so these assert the exact
query and body the API receives. The FM contract is easy to get subtly wrong
-- duration_minutes supersedes horizon, n_runs is capped server-side, and
model_args keys are rejected rather than ignored -- so the payload shape is
what is worth pinning.
"""

import pytest

from simudyne.resources.fm import (
    AVAILABLE_DATA_PATH,
    JOBS_PATH,
    LIVE_PATH,
    MODELS_PATH,
    RUN_PATH,
    TERMINAL_STATUSES,
    FmResource,
)


class FakeClient:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0) if self._responses else {}

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def fm():
    res = FmResource(FakeClient())
    return res


class TestDiscovery:
    def test_models_hits_the_models_path(self, fm):
        fm.models()
        method, path, _ = fm._client.last
        assert (method, path) == ("GET", MODELS_PATH)

    def test_models_returns_the_api_shape_unchanged(self):
        # The endpoint answers {"models": [...]}, not a bare list. Returning it
        # verbatim keeps every resource method consistent -- raw JSON through.
        client = FakeClient(responses=[{"models": [{"model_id": "m1"}]}])
        out = FmResource(client).models()
        assert out["models"][0]["model_id"] == "m1"

    def test_available_data_omits_unset_filters(self, fm):
        fm.available_data()
        _, path, kwargs = fm._client.last
        assert path == AVAILABLE_DATA_PATH
        # limit/offset have real defaults and are always sent; nothing else is
        assert kwargs["params"] == {"limit": 50, "offset": 0}

    def test_available_data_passes_model_id_so_markets_are_filtered(self, fm):
        fm.available_data(model_id="tradefm-hkex", q="700", date="2025-09-02")
        params = fm._client.last[2]["params"]
        assert params["model_id"] == "tradefm-hkex"
        assert params["q"] == "700"
        assert params["date"] == "2025-09-02"


class TestRunPayload:
    def _run(self, fm, **kw):
        base = dict(
            model_id="tradefm-hkex",
            symbol="700",
            cal_date="2025-09-02",
            provider="bmll",
            exchange="hkex_securities",
        )
        base.update(kw)
        fm.run(**base)
        return fm._client.last[2]["json"]

    def test_targets_run_path_with_required_defaults(self, fm):
        body = self._run(fm)
        assert fm._client.last[:2] == ("POST", RUN_PATH)
        assert body["model_id"] == "tradefm-hkex"
        assert body["n_runs"] == 1
        assert body["seed"] == 42

    def test_unset_optionals_are_omitted_not_nulled(self, fm):
        body = self._run(fm)
        for field in ("duration_minutes", "horizon", "device", "prompt",
                      "model_args", "exec_algos"):
            assert field not in body, f"{field} must be omitted when unset"

    def test_duration_and_horizon_are_both_forwarded_when_given(self, fm):
        # The API decides precedence (duration_minutes wins); the SDK must not
        # silently drop one, or a caller cannot express the legacy form.
        body = self._run(fm, duration_minutes=30, horizon=500)
        assert body["duration_minutes"] == 30
        assert body["horizon"] == 500

    def test_model_args_pass_through(self, fm):
        body = self._run(fm, model_args={"temperature": 0.8})
        assert body["model_args"] == {"temperature": 0.8}

    def test_empty_model_args_is_omitted(self, fm):
        body = self._run(fm, model_args={})
        assert "model_args" not in body

    def test_css_exec_algo_orders_are_serialized_like_the_abm(self, fm):
        pd = pytest.importorskip("pandas")
        idx = pd.date_range("2025-09-02 09:30", periods=3, freq="1min")
        orders = pd.Series([10, 20, 30], index=idx)
        body = self._run(fm, exec_algos=[{"type": "css", "orders": orders}])
        sent = body["exec_algos"][0]["orders"]
        # A pd.Series is not JSON-serializable; it must arrive as str -> int
        assert isinstance(sent, dict)
        assert all(isinstance(k, str) and isinstance(v, int) for k, v in sent.items())
        assert sum(sent.values()) == 60


class TestJobsAndLive:
    def test_job_status_path(self, fm):
        fm.job_status("job-1")
        assert fm._client.last[:2] == ("GET", f"{JOBS_PATH}/job-1/status")

    def test_job_logs_path(self, fm):
        fm.job_logs("job-1")
        assert fm._client.last[:2] == ("GET", f"{JOBS_PATH}/job-1/logs")

    def test_live_targets_live_path_and_omits_unset(self, fm):
        fm.live(model_id="tradefm-hkex")
        method, path, kwargs = fm._client.last
        assert (method, path) == ("POST", LIVE_PATH)
        assert kwargs["json"] == {"model_id": "tradefm-hkex", "seed": 42}

    def test_only_complete_and_failed_are_terminal(self):
        # A poller loops on "not terminal", so a new waiting state must not
        # accidentally read as finished.
        assert set(TERMINAL_STATUSES) == {"complete", "failed"}
        for waiting in ("queued", "provisioning", "starting", "running"):
            assert waiting not in TERMINAL_STATUSES
