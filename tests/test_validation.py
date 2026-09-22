"""Tests for the validation resource.

No network: the client's ``_request`` is replaced with a recorder, so these
assert the exact payload the API receives and the exact result handed back.

The surface is one call — ``run`` submits, waits and returns the finished
result — so most of what is worth pinning is what it sends, what it refuses to
send, and what it does with the response.
"""

import base64
import json

import pytest

from simudyne.resources.validation import MAX_SIM_FILES, ValidationResource


class FakeClient:
    """Records calls and replays queued responses."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0) if self._responses else {}


SIM_IDS = ["omd:hkex_securities:700.HK:2025-12-22:abc:normal:baseline:0000"]
IDENTITY = dict(symbol="700.HK", date="2025-12-22", provider="omd",
                exchange="hkex_securities")

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _run(responses, **kwargs):
    client = FakeClient(responses)
    result = ValidationResource(client).run(
        sim_ids=SIM_IDS, **{**IDENTITY, **kwargs}
    )
    return client, result


def _done(**extra):
    return {"job_id": "v1", "status": "completed", **extra}


class TestIdentityIsRequired:
    """The same symbol exists under two providers with different tick sizes,
    so the symbol alone never identified an instrument."""

    @pytest.mark.parametrize("missing", ["symbol", "date", "provider", "exchange"])
    def test_every_identity_field_is_required(self, missing):
        kwargs = {k: v for k, v in IDENTITY.items() if k != missing}
        with pytest.raises(TypeError):
            ValidationResource(FakeClient()).run(sim_ids=SIM_IDS, **kwargs)


class TestWhatToValidate:
    def test_sim_ids_go_as_json(self):
        client, _ = _run([{"job_id": "v1"}])
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/validation/run")
        assert kwargs["json"]["sim_ids"] == SIM_IDS
        assert kwargs["json"]["provider"] == "omd"

    def test_sim_files_go_as_multipart_to_the_upload_route(self):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            sim_files=[("a.parquet", b"x"), ("b.parquet", b"y")], **IDENTITY
        )
        method, path, kwargs = client.calls[0]
        assert (method, path) == ("POST", "/validation/run/upload")
        assert len(kwargs["files"]) == 2
        assert json.loads(kwargs["data"]["config"])["n_levels"] == 10

    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({}, "exactly one"),
            ({"sim_ids": SIM_IDS, "sim_files": [("a", b"x")]}, "exactly one"),
            ({"sim_ids": []}, "must not be empty"),
            ({"sim_ids": SIM_IDS * (MAX_SIM_FILES + 1)}, "Maximum 25"),
            ({"sim_ids": SIM_IDS, "ticksize": 0}, "ticksize must be positive"),
            ({"sim_ids": SIM_IDS, "n_levels": 0}, "at least 1"),
        ],
    )
    def test_bad_input_is_refused_before_any_request(self, kwargs, match):
        client = FakeClient()
        with pytest.raises(ValueError, match=match):
            ValidationResource(client).run(**{**IDENTITY, **kwargs})
        assert client.calls == []


class TestMetricFlags:
    def test_unset_flags_are_omitted_so_the_tier_default_applies(self):
        client, _ = _run([{"job_id": "v1"}])
        config = client.calls[0][2]["json"]["config"]
        # Sending these as null would override the server-side tier default.
        for flag in ("statistical", "stylised_facts", "impact",
                     "volume_correlation", "fid", "mind"):
            assert flag not in config, f"{flag} must be omitted when unset"
        assert config == {"n_levels": 10}

    @pytest.mark.parametrize(
        "flag,value",
        [("statistical", False), ("stylised_facts", True), ("impact", False),
         ("volume_correlation", True), ("fid", False), ("mind", True),
         ("lob", True), ("sample_period", "100ms"),
         ("match_generated_sample", True),
         ("plots", ["statistical.radar"])],
    )
    def test_explicit_options_are_forwarded(self, flag, value):
        client, _ = _run([{"job_id": "v1"}], **{flag: value})
        assert client.calls[0][2]["json"]["config"][flag] == value

    def test_the_legacy_aliases_are_gone(self):
        """run_* and l2_only/plot_data were two names for one thing."""
        for dead in ("run_metrics", "run_impact", "run_stylised_facts",
                     "run_inception_distances", "l2_only", "plot_data",
                     "historical_output"):
            with pytest.raises((TypeError, ValueError)):
                ValidationResource(FakeClient()).run(
                    sim_ids=SIM_IDS, **IDENTITY, **{dead: True}
                )


class TestSubmitOnly:
    """run submits and returns. A real day takes minutes, which is far too
    long to hold a request open, so status is get_job's job."""

    def test_it_returns_the_submission_without_waiting(self):
        client, result = _run([{"job_id": "v1", "status": "pending"}])
        assert result == {"job_id": "v1", "status": "pending"}
        assert [c[0] for c in client.calls] == ["POST"]

    def test_a_missing_job_id_is_an_error(self):
        with pytest.raises(ValueError, match="no job_id"):
            _run([{"detail": "nope"}])

    def test_it_does_not_poll(self):
        assert not hasattr(ValidationResource, "_await")
        import inspect

        params = inspect.signature(ValidationResource.run).parameters
        assert "poll_interval" not in params
        assert "timeout" not in params


class TestPlots:
    """Figures arrive with the result, so get_job is what writes them."""

    @staticmethod
    def _fetch(responses, **kwargs):
        client = FakeClient(responses)
        return ValidationResource(client).get_job("v1", **kwargs)

    def test_plots_requested_on_the_run_go_in_the_config(self):
        client, _ = _run([{"job_id": "v1"}], plots=["statistical.radar"])
        assert client.calls[0][2]["json"]["config"]["plots"] == ["statistical.radar"]

    def test_nothing_is_written_when_the_job_has_no_plots(self, tmp_path):
        job = self._fetch([_done()], plot_dir=str(tmp_path))
        assert "plot_paths" not in job
        assert list(tmp_path.iterdir()) == []

    def test_plots_are_written_to_plot_dir(self, tmp_path):
        target = tmp_path / "figs"
        job = self._fetch(
            [_done(plots={"distances": [{"name": "l1", "content_base64": PNG}]})],
            plot_dir=str(target),
        )
        assert job["plot_paths"] == [str(target / "l1.png")]
        assert (target / "l1.png").read_bytes().startswith(b"\x89PNG")

    def test_plot_dir_is_created_if_absent(self, tmp_path):
        target = tmp_path / "a" / "b"
        self._fetch(
            [_done(plots={"distances": [{"name": "l1", "content_base64": PNG}]})],
            plot_dir=str(target),
        )
        assert (target / "l1.png").is_file()

    def test_without_plot_dir_they_land_in_the_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        job = self._fetch(
            [_done(plots={"distances": [{"name": "radar", "content_base64": PNG}]})]
        )
        assert job["plot_paths"] == [str(tmp_path / "radar.png")]
        assert (tmp_path / "radar.png").is_file()


class TestOneEntryPoint:
    def test_the_extra_run_methods_are_gone(self):
        for dead in ("run_pipeline", "run_upload", "display_plots",
                     "inception_distances"):
            assert not hasattr(ValidationResource, dead)

    def test_retrieval_still_works(self):
        client = FakeClient([{"job_id": "v1"}, {"jobs": [], "total": 0}])
        res = ValidationResource(client)
        res.get_job("v1")
        res.list_jobs(limit=5)
        assert client.calls[0][:2] == ("GET", "/validation/jobs/v1")
        assert client.calls[1][2]["params"] == {"limit": 5}


class TestSimulatedFrameShapes:
    """sim_files takes a path, a (name, bytes) pair, or a DataFrame."""

    def _files_sent(self, entries):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(sim_files=entries, **IDENTITY)
        return client.calls[0][2]["files"]

    def test_pair(self):
        part = self._files_sent([("a.parquet", b"x")])[0][1]
        assert part == ("a.parquet", b"x", "application/octet-stream")

    def test_path(self, tmp_path):
        p = tmp_path / "sim.parquet"
        p.write_bytes(b"data")
        part = self._files_sent([str(p)])[0][1]
        assert part == ("sim.parquet", b"data", "application/octet-stream")

    def test_each_frame_gets_its_own_name(self):
        pd = pytest.importorskip("pandas")
        frames = [pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})]
        names = [f[1][0] for f in self._files_sent(frames)]
        assert names == ["sim_0.parquet", "sim_1.parquet"]


class TestNamedPopulations:
    """Runs can be named so the results compare populations, not an average."""

    def test_grouped_sim_ids_go_as_a_mapping(self):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            sim_ids={"fm": ["a"], "abm": ["b", "c"]}, **IDENTITY
        )
        assert client.calls[0][2]["json"]["sim_ids"] == {
            "fm": ["a"],
            "abm": ["b", "c"],
        }

    def test_the_total_is_what_is_capped(self):
        client = FakeClient()
        with pytest.raises(ValueError, match="Maximum 25"):
            ValidationResource(client).run(
                sim_ids={"a": ["x"] * 13, "b": ["y"] * 13}, **IDENTITY
            )
        assert client.calls == []

    def test_grouped_uploads_travel_flat_with_the_grouping_beside_them(self):
        """Multipart has no nesting, so the groups go in the config."""
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            sim_files={"fm": [("a.parquet", b"x")],
                       "abm": [("b.parquet", b"y"), ("c.parquet", b"z")]},
            **IDENTITY,
        )
        kwargs = client.calls[0][2]
        assert len(kwargs["files"]) == 3
        assert json.loads(kwargs["data"]["config"])["sim_groups"] == {
            "fm": [0], "abm": [1, 2]
        }

    def test_an_ungrouped_upload_carries_no_grouping(self):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(
            sim_files=[("a.parquet", b"x")], **IDENTITY
        )
        assert "sim_groups" not in json.loads(client.calls[0][2]["data"]["config"])


class TestPlotEverything:
    """plots says it all: there is no second way to ask for every figure."""

    def test_true_is_forwarded(self):
        client, _ = _run([{"job_id": "v1"}], plots=True)
        assert client.calls[0][2]["json"]["config"]["plots"] is True

    def test_nothing_is_sent_when_not_asked_for(self):
        client, _ = _run([{"job_id": "v1"}])
        assert "plots" not in client.calls[0][2]["json"]["config"]

    def test_plot_all_is_gone(self):
        with pytest.raises(TypeError):
            _run([{"job_id": "v1"}], plot_all=True)


class TestGroupShape:
    """A group's value is a list of runs. A bare string is not one.

    ``{"fm": "one.parquet"}`` is the natural thing to write for a group of
    one, and it used to count the path's characters as runs and fail with
    "Maximum 25 simulations per validation job" — a number the caller never
    wrote anywhere.
    """

    @staticmethod
    def _submit(**kwargs):
        return ValidationResource(FakeClient([{"job_id": "v1"}])).run(
            **{**IDENTITY, **kwargs}
        )

    def test_a_string_names_itself_not_the_file_count(self):
        with pytest.raises(ValueError, match=r"sim_files\['fm'\] must be a list"):
            self._submit(sim_files={"fm": "one.parquet"})

    def test_the_message_shows_the_fix(self):
        with pytest.raises(ValueError, match=r"write \['one.parquet'\]"):
            self._submit(sim_files={"fm": "one.parquet"})

    def test_sim_ids_groups_are_checked_the_same_way(self):
        with pytest.raises(ValueError, match=r"sim_ids\['abm'\] must be a list"):
            self._submit(sim_ids={"abm": "sim_abc"})

    def test_a_non_iterable_group_is_named_plainly(self):
        with pytest.raises(ValueError, match=r"not NoneType"):
            self._submit(sim_ids={"abm": None})

    def test_a_real_list_still_passes(self):
        client = FakeClient([{"job_id": "v1"}])
        ValidationResource(client).run(sim_ids={"abm": ["a", "b"]}, **IDENTITY)
        assert client.calls[0][2]["json"]["sim_ids"] == {"abm": ["a", "b"]}

    def test_the_count_still_catches_too_many(self):
        with pytest.raises(ValueError, match="Maximum 25"):
            self._submit(sim_ids={"a": ["x"] * 13, "b": ["y"] * 13})
