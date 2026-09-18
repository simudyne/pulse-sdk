"""Tests for the validation resource's request payloads and score handling.

No network: the client's _request is replaced with a recorder, so these assert
the exact payload the API receives — which is what actually broke when
pulse-check 1.8.0 dropped rescale_volumes/lot_size and made run_fid gate both
inception distances.
"""

import pytest

from simudyne.resources.validation import ValidationResource


class FakeClient:
    """Records calls and replays queued responses."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0) if self._responses else {}


SIM_IDS = ["omd:hkex_securities:700.HK:2025-12-22:abc:normal:baseline:0000"]


class TestRunPayload:
    def test_unset_flags_are_omitted_so_the_tier_default_applies(self):
        client = FakeClient([{"job_id": "v1", "status": "pending"}])
        ValidationResource(client).run("700.HK", "2025-12-22", SIM_IDS)

        _, path, kwargs = client.calls[0]
        config = kwargs["json"]["config"]
        assert path == "/validation/run"
        # Sending these as null would override the server-side tier default.
        for flag in ("run_metrics", "run_impact",
                     "run_stylised_facts", "plot_data"):
            assert flag not in config, f"{flag} must be omitted when unset"
        # run_inception_distances is NOT tri-state: it defaults to True and is
        # always sent, as the API's run_fid field.
        assert config == {"n_levels": 10, "l2_only": False, "run_fid": True}

    def test_explicit_flags_are_sent(self):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            "700.HK", "2025-12-22", SIM_IDS, run_impact=False
        )

        config = client.calls[0][2]["json"]["config"]
        # An explicit False must survive — it is how a demo user skips a pass.
        assert config["run_impact"] is False

    def test_inception_distances_can_be_opted_out(self):
        """Non-demo tiers should be able to skip the embedding pass."""
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            "700.HK", "2025-12-22", SIM_IDS, run_inception_distances=False
        )
        assert client.calls[0][2]["json"]["config"]["run_fid"] is False

    def test_old_run_fid_kwarg_is_rejected(self):
        """Renamed to run_inception_distances — the old spelling must fail loudly."""
        with pytest.raises(TypeError):
            ValidationResource(FakeClient([{}])).run(
                "700.HK", "2025-12-22", SIM_IDS, run_fid=True
            )

    def test_removed_params_are_not_accepted(self):
        """rescale_volumes/lot_size went away with pulse-check 1.8.0."""
        resource = ValidationResource(FakeClient([{}]))
        with pytest.raises(TypeError):
            resource.run("700.HK", "2025-12-22", SIM_IDS, rescale_volumes=True)
        with pytest.raises(TypeError):
            resource.run("700.HK", "2025-12-22", SIM_IDS, lot_size=100)

    def test_provider_and_exchange_omitted_unless_given(self):
        client = FakeClient([{}, {}])
        r = ValidationResource(client)
        r.run("700.HK", "2025-12-22", SIM_IDS)
        assert "provider" not in client.calls[0][2]["json"]

        r.run("700.HK", "2025-12-22", SIM_IDS, provider="omd", exchange="lse")
        payload = client.calls[1][2]["json"]
        assert payload["provider"] == "omd" and payload["exchange"] == "lse"


class TestInceptionDistances:
    def _completed(self, **extra):
        return {"job_id": "v1", "status": "completed", **extra}

    def test_forces_fid_on_and_everything_else_off(self):
        client = FakeClient([
            {"job_id": "v1", "status": "pending"},
            self._completed(mind_scores=[12.5], fid_scores=[8.25]),
        ])
        out = ValidationResource(client).inception_distances(
            "700.HK", "2025-12-22", SIM_IDS, poll_interval=0
        )

        config = client.calls[0][2]["json"]["config"]
        assert config["run_fid"] is True  # wire name for run_inception_distances
        assert config["run_metrics"] is False
        assert config["run_impact"] is False
        assert config["run_stylised_facts"] is False

        assert out["mind"] == [12.5]
        assert out["fid"] == [8.25]
        assert out["sim_ids"] == SIM_IDS
        assert out["job_id"] == "v1"

    def test_none_scores_are_preserved_to_keep_indexing_aligned(self):
        two = SIM_IDS * 2
        client = FakeClient([
            {"job_id": "v1", "status": "pending"},
            self._completed(mind_scores=[12.5, None], fid_scores=[8.25, None]),
        ])
        out = ValidationResource(client).inception_distances(
            "700.HK", "2025-12-22", two, poll_interval=0
        )
        assert out["mind"] == [12.5, None]
        assert len(out["mind"]) == len(out["sim_ids"])

    def test_missing_scores_raise_rather_than_returning_empty(self):
        """A skipped pass or a non-demo key is silent in the raw response."""
        client = FakeClient([
            {"job_id": "v1", "status": "pending"},
            self._completed(mind_scores=None, fid_scores=None),
        ])
        with pytest.raises(RuntimeError, match="no inception distances"):
            ValidationResource(client).inception_distances(
                "700.HK", "2025-12-22", SIM_IDS, poll_interval=0
            )


class TestRunPipeline:
    def test_raises_on_failed_job(self):
        client = FakeClient([
            {"job_id": "v1", "status": "pending"},
            {"job_id": "v1", "status": "failed", "error": "boom"},
        ])
        with pytest.raises(RuntimeError, match="boom"):
            ValidationResource(client).run_pipeline(
                "700.HK", "2025-12-22", SIM_IDS, poll_interval=0
            )

    def test_returns_the_completed_result(self):
        client = FakeClient([
            {"job_id": "v1", "status": "pending"},
            {"job_id": "v1", "status": "running"},
            {"job_id": "v1", "status": "completed", "distances": {"spread": {}}},
        ])
        result = ValidationResource(client).run_pipeline(
            "700.HK", "2025-12-22", SIM_IDS, poll_interval=0
        )
        assert result["status"] == "completed"
        assert "spread" in result["distances"]


class TestNewValidationOptions:
    """pulse-check 1.10.0 areas, sampling and plot selection.

    Everything here is opt-in: a job naming none of it must send exactly the
    config it sent before, so existing callers are untouched.
    """

    BASE = dict(
        run_metrics=None,
        run_impact=None,
        run_inception_distances=True,
        run_stylised_facts=None,
        plot_data=None,
        n_levels=10,
        l2_only=False,
    )

    def test_naming_nothing_new_is_unchanged(self):
        from simudyne.resources.validation import _build_config

        assert _build_config(**self.BASE) == {
            "n_levels": 10,
            "l2_only": False,
            "run_fid": True,
        }

    @pytest.mark.parametrize(
        "name,value",
        [
            ("statistical", False),
            ("stylised_facts", True),
            ("impact", False),
            ("volume_correlation", True),
            ("fid", False),
            ("mind", True),
            ("lob", True),
            ("sample_period", "100ms"),
            ("match_generated_sample", True),
            ("historical_output", True),
            ("plots", ["volume_correlation.levels"]),
        ],
    )
    def test_option_is_forwarded(self, name, value):
        from simudyne.resources.validation import _build_config

        assert _build_config(**self.BASE, **{name: value})[name] == value

    def test_unknown_option_is_rejected_by_name(self):
        from simudyne.resources.validation import _build_config

        with pytest.raises(ValueError, match="Unknown validation option"):
            _build_config(**self.BASE, volume_corelation=True)

    def test_none_is_omitted_not_sent_as_null(self):
        """Absence means 'use my tier's default'; null would not."""
        from simudyne.resources.validation import _build_config

        assert "volume_correlation" not in _build_config(
            **self.BASE, volume_correlation=None
        )


class TestSimulatedFrameShapes:
    """run_upload takes a path, a (name, bytes) pair, or a DataFrame."""

    def test_tuple_passes_through(self):
        from simudyne.resources.validation import _frame_to_parquet

        assert _frame_to_parquet(("a.parquet", b"raw"), 0) == ("a.parquet", b"raw")

    def test_path(self, tmp_path):
        import pandas as pd

        from simudyne.resources.validation import _frame_to_parquet

        p = tmp_path / "run.parquet"
        pd.DataFrame({"a": [1, 2]}).to_parquet(p)
        name, content = _frame_to_parquet(str(p), 0)
        assert name == "run.parquet"
        assert content[:4] == b"PAR1"

    def test_pandas_frame(self):
        import pandas as pd

        from simudyne.resources.validation import _frame_to_parquet

        name, content = _frame_to_parquet(pd.DataFrame({"a": [1, 2]}), 3)
        assert name == "sim_3.parquet"
        assert content[:4] == b"PAR1"

    def test_polars_frame(self):
        pl = pytest.importorskip("polars")

        from simudyne.resources.validation import _frame_to_parquet

        name, content = _frame_to_parquet(pl.DataFrame({"a": [1, 2]}), 1)
        assert name == "sim_1.parquet"
        assert content[:4] == b"PAR1"

    def test_each_frame_gets_its_own_name(self):
        """Distinct names, or the multipart upload collapses the runs."""
        import pandas as pd

        from simudyne.resources.validation import _frame_to_parquet

        frames = [pd.DataFrame({"a": [i]}) for i in range(3)]
        names = [_frame_to_parquet(f, i)[0] for i, f in enumerate(frames)]
        assert len(set(names)) == 3
