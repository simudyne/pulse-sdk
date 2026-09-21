"""
Validation Resource for the Pulse SDK.

Compares simulated LOB data against a historical day using distributional
metrics, impact response, Cont's stylised facts, cross-level volume
correlation, and the MIND/FID inception distances on DeepLOB embeddings.

Submit, then poll::

    job = client.validation.run(
        symbol="BARC", date="2026-06-17", provider="bmll", exchange="lse",
        sim_ids=[...], ticksize=0.05,
    )
    result = client.validation.get_job(job["job_id"])
    result["distances"]["spread"]["l1"]        # per simulation
    result["stylised_fact_verdicts"]["heavy_tails"]

``run`` submits and returns; a validation of a real day takes minutes, so
``get_job`` is the status endpoint you call until it is done. ``list_jobs``
reaches past runs.

Selecting metrics
-----------------
One flag per metric — ``statistical``, ``stylised_facts``, ``impact``,
``volume_correlation``, ``fid``, ``mind``. Left as ``None`` each takes the
default for your tier, resolved server-side, so naming none behaves exactly as
your account is entitled to. Pass ``False`` to skip an expensive pass or
``True`` to force one on.

The historical gate
-------------------
Whether the historical half of the comparison comes back — the series in the
JSON *and* the historical trace on any rendered plot — is decided by your tier,
not by a parameter here. What is never gated: the L1 and Wasserstein
``distances``, the FID and MIND scores, and the true/false
``stylised_fact_verdicts`` for both the historical day and each simulation.
Those are derived scalars and booleans, not series, so every tier receives
them.
"""

import json
from pathlib import Path


RUN_PATH = "/validation/run"
UPLOAD_PATH = "/validation/run/upload"
JOBS_PATH = "/validation/jobs"

#: The API rejects more per job; checked client-side so a 26-file submission
#: fails before any bytes are uploaded.
MAX_SIM_FILES = 25

#: One flag per area of checking. Left unset each takes the server's default.
_AREA_FLAGS = (
    "statistical",
    "stylised_facts",
    "impact",
    "volume_correlation",
    "fid",
    "mind",
)

#: ``lob`` marks the frames as L2 snapshots, which switches off anything
#: needing the message stream; ``sample_period`` and ``match_generated_sample``
#: set the grid the book is resampled onto; ``plots`` is False, True, or a list
#: of plot ids.
_EXTRA_FIELDS = ("lob", "sample_period", "match_generated_sample", "plots")


def _frame_to_parquet(entry, index: int):
    """Normalise one simulated run to ``(filename, parquet bytes)``.

    Accepts a path, a ``(filename, bytes)`` pair, or a polars / pandas
    DataFrame, which is written to parquet in memory. The frame must be pulse
    format -- the same shape the engine writes to ``sim_data.parquet`` -- which
    the server validates; sending something else fails there, not here.
    """
    import io

    if isinstance(entry, tuple):
        return entry

    # Duck-typed rather than imported: neither polars nor pandas is a hard
    # dependency of the SDK, and importing one to test for the other would
    # make it one.
    writer = getattr(entry, "write_parquet", None)      # polars
    if writer is not None:
        buf = io.BytesIO()
        writer(buf)
        return f"sim_{index}.parquet", buf.getvalue()

    writer = getattr(entry, "to_parquet", None)          # pandas
    if writer is not None:
        buf = io.BytesIO()
        writer(buf, index=False)
        return f"sim_{index}.parquet", buf.getvalue()

    path = Path(entry)
    return path.name, path.read_bytes()


def _build_config(n_levels, **flags) -> dict:
    """The validation config as the API expects it.

    Flags left as ``None`` are omitted rather than sent as null: the API reads
    absence as "use my tier's default", and an explicit null would not do that.
    """
    config = {"n_levels": n_levels}
    for name in _AREA_FLAGS + _EXTRA_FIELDS:
        value = flags.get(name)
        if value is not None:
            config[name] = value

    unknown = set(flags) - set(_AREA_FLAGS) - set(_EXTRA_FIELDS)
    if unknown:
        raise ValueError(
            f"Unknown validation option(s): {sorted(unknown)}. "
            f"Valid: {sorted(_AREA_FLAGS + _EXTRA_FIELDS)}"
        )
    return config


def _save_plots(result: dict, plot_dir=None) -> list:
    """Write the returned figures to disk and return the paths written.

    The API sends rendered plots base64-encoded in the response. Left to
    itself that is bytes you cannot look at, so when plots were asked for they
    are written out: to ``plot_dir`` when given, otherwise the current
    directory. The directory is created if it does not exist.
    """
    import base64

    target = Path(plot_dir) if plot_dir is not None else Path.cwd()
    target.mkdir(parents=True, exist_ok=True)

    written = []
    for category, entries in (result.get("plots") or {}).items():
        for entry in entries or []:
            content = entry.get("content_base64")
            if not content:
                continue
            path = target / f"{entry.get('name') or category}.png"
            path.write_bytes(base64.b64decode(content))
            written.append(str(path))
    return written


class ValidationResource:
    """Validate simulated market data against a historical day."""

    def __init__(self, client):
        self._client = client

    def run(
        self,
        symbol: str,
        date: str,
        provider: str,
        exchange: str,
        *,
        sim_ids=None,
        sim_files=None,
        ticksize: float = 1.0,
        statistical=None,
        stylised_facts=None,
        impact=None,
        volume_correlation=None,
        fid=None,
        mind=None,
        lob=None,
        sample_period=None,
        match_generated_sample=None,
        n_levels: int = 10,
        plots=None,
    ) -> dict:
        """Submit a validation job.

        Returns as soon as the job is accepted. Poll :meth:`get_job` for
        status and, once it is complete, the result — a validation of a real
        day takes minutes, which is far too long to hold a request open.

        Parameters
        ----------
        symbol : str
            Trading symbol, e.g. ``"BARC"`` or ``"700.HK"``.
        date : str
            Calibration date, ``"YYYY-MM-DD"``. The historical day compared
            against.
        provider : str
            Data provider, ``"bmll"`` or ``"omd"``. Required: the same symbol
            exists under both with different dates and tick sizes, so
            ``(symbol, provider, exchange)`` is the identity, not the symbol.
        exchange : str
            Exchange, e.g. ``"lse"`` or ``"hkex_securities"``.
        sim_ids : list of str, optional
            Platform simulation IDs, 1 to 25. Exactly one of ``sim_ids`` or
            ``sim_files`` is required.
        sim_files : list, optional
            Your own simulated runs, up to 25: paths, ``(filename, bytes)``
            pairs, or polars / pandas DataFrames in pulse format. The
            historical side is fetched for you.
        ticksize : float, default 1.0
            Minimum price increment. Should match the instrument.
        statistical, stylised_facts, impact, volume_correlation, fid, mind : bool, optional
            Whether to run each area. ``None`` uses your tier's default.
        lob : bool, optional
            The frames are L2 snapshots. Anything needing the message stream
            is skipped, with the reason reported in
            ``metadata["areas_skipped"]``.
        sample_period : str, optional
            The grid the book is resampled onto in lob mode, e.g. ``"1s"``.
            Omitted, the cadence is read off your generated frames; if those
            are event-level there is no grid to match and nothing is
            resampled.
        match_generated_sample : bool, optional
            Match the generated frames' grid even when ``sample_period`` is
            given.
        n_levels : int, default 10
            Book levels to measure over.
        plots : bool or list of str, optional
            ``None`` or ``False`` for none, ``True`` for every figure, or plot
            ids such as ``["statistical.radar", "stylised_facts.overall"]``.
            Rendered server-side; :meth:`get_job` writes them to disk.

        Returns
        -------
        dict
            ``{"job_id": str, "status": str, "message": str}``. Pass the
            job_id to :meth:`get_job`.

        Raises
        ------
        ValueError
            If the parameters are invalid.
        """
        if (sim_ids is None) == (sim_files is None):
            raise ValueError("Pass exactly one of sim_ids or sim_files")
        if sim_ids is not None and not sim_ids:
            raise ValueError("sim_ids must not be empty")
        if sim_files is not None and not sim_files:
            raise ValueError("sim_files must not be empty")
        count = len(sim_ids if sim_ids is not None else sim_files)
        if count > MAX_SIM_FILES:
            raise ValueError(f"Maximum {MAX_SIM_FILES} simulations per validation job")
        if ticksize <= 0:
            raise ValueError("ticksize must be positive")
        if n_levels < 1:
            raise ValueError("n_levels must be at least 1")

        config = _build_config(
            n_levels,
            statistical=statistical,
            stylised_facts=stylised_facts,
            impact=impact,
            volume_correlation=volume_correlation,
            fid=fid,
            mind=mind,
            lob=lob,
            sample_period=sample_period,
            match_generated_sample=match_generated_sample,
            plots=plots,
        )

        if sim_ids is not None:
            submitted = self._client._request(
                "POST",
                RUN_PATH,
                json={
                    "symbol": symbol,
                    "date": date,
                    "provider": provider,
                    "exchange": exchange,
                    "sim_ids": list(sim_ids),
                    "ticksize": ticksize,
                    "config": config,
                },
            )
        else:
            files = [
                ("sim_files", _frame_to_parquet(entry, i))
                for i, entry in enumerate(sim_files)
            ]
            submitted = self._client._request(
                "POST",
                UPLOAD_PATH,
                files=files,
                data={
                    "symbol": symbol,
                    "date": date,
                    "provider": provider,
                    "exchange": exchange,
                    "ticksize": str(ticksize),
                    "config": json.dumps(config),
                },
            )

        if not (submitted or {}).get("job_id"):
            raise ValueError(f"Validation API returned no job_id: {submitted}")
        return submitted


    def get_job(self, job_id: str, plot_dir=None) -> dict:
        """Fetch a validation job's status, and its result once it is done.

        This is the status endpoint: call it until ``status`` is
        ``"completed"`` or ``"failed"``.

        Parameters
        ----------
        job_id : str
            From :meth:`run`.
        plot_dir : str or Path, optional
            Where to write any figures the job rendered. Defaults to the
            current directory; created if it does not exist. Only has an
            effect once the job is complete and only if ``plots`` was set on
            the run. The paths written come back in ``plot_paths``.

        Returns
        -------
        dict
            ``job_id``, ``status``, ``symbol``, ``date`` and, once complete:
            ``metadata``, ``distances``, ``distributions``,
            ``impact_response``, ``stylised_facts``,
            ``stylised_fact_verdicts``, ``volume_correlation``,
            ``fid_scores``, ``mind_scores`` — enough to rebuild every figure —
            plus ``plot_paths`` when figures were written.
        """
        job = self._client._request("GET", f"{JOBS_PATH}/{job_id}")
        if (job or {}).get("plots"):
            job["plot_paths"] = _save_plots(job, plot_dir)
        return job

    def list_jobs(self, limit: int = 50) -> dict:
        """List your validation jobs, newest first.

        Parameters
        ----------
        limit : int, default 50
            Maximum number of jobs to return.

        Returns
        -------
        dict
            ``{"jobs": list, "total": int}``.
        """
        return self._client._request("GET", JOBS_PATH, params={"limit": limit})
