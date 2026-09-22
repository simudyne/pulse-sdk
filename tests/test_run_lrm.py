"""Tests for SimulationResource.run_lrm.

The HTTP layer is stubbed, so these check the payload the SDK builds and the
endpoint it targets, not a live service.
"""

import pytest

from simudyne.resources.simulation import LRM_RUN_PATH, SimulationResource


class _StubClient:
    """Captures the request the resource makes."""

    def __init__(self):
        self.calls = []

    def _request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        return {"job_id": "job-abc", "total_jobs": 250}

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def resource():
    client = _StubClient()
    res = SimulationResource(client)
    res._stub = client
    return res


def _run(resource, **kw):
    base = dict(
        symbol="700.HK",
        cal_date="2025-09-02",
        provider="omd",
        exchange="hkex_securities",
        order_sizes=[500, 1000, 2000, 4000],
    )
    base.update(kw)
    return resource.run_lrm(**base)


class TestEndpoint:

    def test_posts_to_the_lrm_path(self, resource):
        _run(resource)
        method, endpoint, _ = resource._stub.last
        assert method == "POST"
        assert endpoint == LRM_RUN_PATH == "/simulation/lrm/run"

    def test_returns_the_server_response(self, resource):
        assert _run(resource)["job_id"] == "job-abc"


class TestPayload:

    def test_carries_the_symbol_identity_and_ladder(self, resource):
        _run(resource)
        payload = resource._stub.last[2]["json"]
        assert payload["symbol"] == "700.HK"
        assert payload["cal_date"] == "2025-09-02"
        assert payload["provider"] == "omd"
        assert payload["exchange"] == "hkex_securities"
        assert payload["order_sizes"] == [500, 1000, 2000, 4000]

    def test_defaults(self, resource):
        _run(resource)
        payload = resource._stub.last[2]["json"]
        assert payload["n_runs"] == 50
        assert payload["seed"] == 42
        assert payload["horizon_mins"] == 60
        assert payload["strategy"] == "vwap"
        assert payload["scenario"] == "normal"

    def test_unset_optionals_are_omitted(self, resource):
        # A null side would override the server default instead of letting the
        # sign of each order size pick the direction.
        _run(resource)
        payload = resource._stub.last[2]["json"]
        assert "side" not in payload
        assert "start_time" not in payload
        assert "scenario_params" not in payload

    def test_optionals_are_sent_when_given(self, resource):
        _run(resource, side="sell", start_time="09:30",
             scenario="flash_crash", scenario_params={"start_time": "10:00"})
        payload = resource._stub.last[2]["json"]
        assert payload["side"] == "sell"
        assert payload["start_time"] == "09:30"
        assert payload["scenario"] == "flash_crash"
        assert payload["scenario_params"] == {"start_time": "10:00"}

    def test_order_sizes_are_copied_not_aliased(self, resource):
        sizes = [500, 1000]
        _run(resource, order_sizes=sizes)
        sizes.append(9999)
        assert resource._stub.last[2]["json"]["order_sizes"] == [500, 1000]

    def test_negative_sizes_pass_through_for_buys(self, resource):
        _run(resource, order_sizes=[-500, -1000])
        assert resource._stub.last[2]["json"]["order_sizes"] == [-500, -1000]


class TestSharedBaselineCost:

    @pytest.mark.parametrize("n_sizes,n_runs,expected", [(4, 50, 250), (8, 50, 450), (8, 25, 225)])
    def test_documented_job_count_matches_the_shared_baseline_shape(
        self, resource, n_sizes, n_runs, expected
    ):
        # n_runs * (1 + n_sizes), the figure the docstring quotes.
        _run(resource, order_sizes=list(range(100, 100 * (n_sizes + 1), 100)), n_runs=n_runs)
        payload = resource._stub.last[2]["json"]
        assert payload["n_runs"] * (1 + len(payload["order_sizes"])) == expected
