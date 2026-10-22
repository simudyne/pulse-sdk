"""
Simulation Resource for the Pulse SDK.

Every simulation goes through here, whichever engine generates it: ``run()``
takes ``engine="abm"`` for the agent-based model or ``engine="fm"`` for a
foundation model, and everything downstream is shared. The two mint the same
canonical ``sim_id`` and differ only in its ``gen_method`` field, so status,
logs and results need no knowledge of which one ran.

Workflow:
    1. Submit a simulation with run() -> returns job_id and sim_ids
    2. Track progress with get_job_status(job_id)
    3. View all past jobs with get_jobs()
    4. Once complete, retrieve results with get_job_results() or get_sim_data()

Calibration is not here — it is a data operation, at
:meth:`~simudyne.resources.data.DataResource.calibrate`.
"""

import io
from pathlib import Path


RUN_PATH = "/simulation/run"
JOBS_PATH = "/simulation/jobs"
RESULTS_PATH = "/simulation/results"
CACHED_PATH = "/simulation/cached"
SAMPLE_PATH = "/simulation/sample"
LRM_PATH = "/simulation/lrm/run"

# Available market scenarios
SCENARIOS = {
    "normal": "No scenario injection - background agents only",
    "flash_crash": "Large rapid SELL depleting bid-side liquidity",
    "buy_panic": "Large rapid BUY depleting ask-side liquidity",
    "gradual_selloff": "Slow sustained SELL over an extended period",
    "trending_up": "Small steady BUY flow producing a persistent uptrend",
    "trending_down": "Small steady SELL flow producing a persistent downtrend",
}

# Scenario parameter defaults.
#
# MUST mirror the builder signatures in the engine's EIB/calcs/scenarios.py —
# SimulationRun backfills any omitted key from those defaults via
# inspect.signature, so a stale copy here misreports what a run will actually
# do. flash_crash/buy_panic drifted once already (22.0/0.19/500ms lingered here
# after the engine moved to 150.0/0.02/100ms), so re-check both when either side
# changes.
SCENARIO_DEFAULTS = {
    "flash_crash": {
        "impact_multiplier": 150.0,
        "order_size_ratio": 0.02,
        "order_freq": "100ms",
        "start_time": "10:30:00",
    },
    "buy_panic": {
        "impact_multiplier": 150.0,
        "order_size_ratio": 0.02,
        "order_freq": "100ms",
        "start_time": "10:30:00",
    },
    "gradual_selloff": {
        "impact_multiplier": 10.0,
        "order_size_ratio": 0.05,
        "order_freq": "5s",
        "start_time": "10:30:00",
    },
    "trending_up": {
        "impact_multiplier": 5.0,
        "order_size_ratio": 0.03,
        "order_freq": "30s",
        "start_time": "10:30:00",
    },
    "trending_down": {
        "impact_multiplier": 5.0,
        "order_size_ratio": 0.03,
        "order_freq": "30s",
        "start_time": "10:30:00",
    },
}



def _csv_text(value) -> str:
    """``rows_csv`` as CSV text: text as given, a ``.csv`` path (str or
    Path) read from disk, a polars or pandas DataFrame written without its
    index (missing values as empty cells)."""
    if isinstance(value, Path) or (
        isinstance(value, str) and "\n" not in value and value.strip().lower().endswith(".csv")
    ):
        path = Path(value).expanduser()
        if not path.is_file():
            raise ValueError(f"rows_csv: no such file {str(path)!r}")
        return path.read_text(encoding="utf-8-sig")
    if isinstance(value, str):
        return value
    if hasattr(value, "write_csv"):  # polars
        return value.write_csv()
    if hasattr(value, "to_csv"):  # pandas
        return value.to_csv(index=False)
    raise TypeError(
        "rows_csv must be CSV text, a path to a .csv file, or a pandas / polars DataFrame, "
        f"not {type(value).__name__}"
    )

class SimulationResource:
    """Run agent-based market simulations and read their results.

    Reached as ``client.simulation``. This is the largest resource in the SDK
    and covers the whole job lifecycle: submit with :meth:`run`, poll with
    :meth:`get_job_status`, then read results either per job
    (:meth:`get_job_results`) or per simulation (:meth:`get_sim_data`).

    It also reads back foundation-model output, since an FM run writes with the
    same conventions — only the ``gen_method`` on the sim differs.

    Running a simulation, and reading jobs, requires a pro- or demo-tier key.
    :meth:`list_cached` and
    :meth:`get_sample_data` are available on every tier.

    Examples
    --------
    Submit, poll, then read:

    >>> import time
    >>> result = client.simulation.run(
    ...     symbol="700.HK",
    ...     cal_date="2025-09-02",
    ...     provider="omd",
    ...     exchange="hkex_securities",
    ...     n_runs=10,
    ...     scenario="flash_crash",
    ... )
    >>> job_id = result["job_id"]
    >>> while True:
    ...     status = client.simulation.get_job_status(job_id)
    ...     print(status["status_summary"])
    ...     if status["is_complete"]:
    ...         break
    ...     time.sleep(20)
    >>> results = client.simulation.get_job_results(job_id)

    Review what you have run:

    >>> jobs = client.simulation.get_jobs()
    >>> print(f"Total jobs: {jobs['total']}")
    """

    
    def __init__(self, client):
        self._client = client

    def _pro_request(self, method: str, endpoint: str, **kwargs):
        """Wrapper for pro-only endpoints — passes errors through from the server."""
        return self._client._request(method, endpoint, **kwargs)

    def run(
        self,
        symbol: str = "",
        cal_date: str = "",
        provider: str = "",
        exchange: str = "",
        engine: str = "abm",
        n_runs: int = None,
        seed: int = 42,
        scenario: str = None,
        scenario_params: dict = None,
        exec_algos: list = None,
        model_id: str = "",
        duration_minutes: float = None,
        horizon: int = None,
        device: str = "",
        model_args: dict = None,
    ):
        """Submit a simulation run to be executed asynchronously.

        One endpoint for both engines. ``engine="abm"`` runs the agent-based
        model against a calibrated day; ``engine="fm"`` runs a foundation model
        against a real day's opening rows. Both mint the same canonical
        ``sim_id`` and are read back through the same results methods — the two
        differ only in the ``gen_method`` field of the id.

        A symbol is identified by four fields: ``provider``, ``exchange``,
        ``symbol`` and ``cal_date``. They are validated against the data
        catalogue *before* the job is accepted, so a run that names data which
        does not exist (or is not calibrated, or the model was not trained for)
        fails here in milliseconds rather than after a worker or a GPU pod has
        started.

        Parameters
        ----------
        symbol : str, optional
            Trading symbol, e.g. "9999.HK" or "700". Required for
            ``engine="abm"``. For ``engine="fm"`` see the all-or-nothing rule
            under `Raises`.
        cal_date : str, optional
            Trading day in YYYY-MM-DD form, e.g. "2025-09-01". For the ABM this
            is the day the model was calibrated on; for an FM it is the day the
            prompt is sliced from.
        provider : str, optional
            Data provider the symbol is sourced from: "omd" or "bmll".
        exchange : str, optional
            Exchange protocol name, e.g. "hkex_securities" or "lse".
        engine : {'abm', 'fm'}, default 'abm'
            Which engine generates the book. ``"fm"`` additionally requires
            ``model_id``; see :meth:`~simudyne.resources.fm.FmResource.models`
            for what is available and what each model accepts.
        n_runs : int, optional
            Independent Monte Carlo runs, each a seeded draw of one
            configuration. Defaults to 5 for the ABM and 1 for an FM, whose
            ceiling is 8 so a job's worst case always fits one GPU.
        seed : int, default 42
            Master seed. Per-run seeds are derived from it identically by both
            engines, so a given ``seed`` and ``n_runs`` reproduce exactly.
        scenario : str, optional
            ABM only, default "normal". Market scenario to inject:

            - "normal": no injection
            - "flash_crash": large rapid SELL depleting bid-side liquidity
            - "buy_panic": large rapid BUY depleting ask-side liquidity
            - "gradual_selloff": slow sustained SELL over an extended period
            - "trending_up" / "trending_down": small steady BUY / SELL

            Scenarios are deliberately not implemented for foundation models;
            passing this with ``engine="fm"`` is an error, not a silent no-op.
        scenario_params : dict, optional
            ABM only. Overrides the scenario's defaults. Checked when the job
            is submitted, including for ``scenario="normal"``; an unknown key
            or an out-of-range value is a 422 naming the field. Keys:

            - impact_multiplier (float, > 0): total volume as a multiple of
              resting liquidity
            - order_size_ratio (float, in (0, 1]): child order size as a
              fraction of liquidity
            - order_freq (str): child order spacing — a number and a unit of
              ms, s, min, m or h, e.g. "500ms", "5s", "1min"
            - start_time (str): when to begin, "HH:MM" or "HH:MM:SS", e.g.
              "10:30:00"

            There is no side: each scenario sets its own direction
            (flash_crash, gradual_selloff and trending_down sell; buy_panic
            and trending_up buy).
        exec_algos : list of dict, optional
            Execution algorithms, same shape and meaning on both engines. Each
            entry needs "type":

            For TWAP/VWAP:

            - type: "twap" or "vwap" (required)
            - order_size: total size in LOTS (multiply by the instrument's
              ``lot_size`` for shares); negative = BUY, positive = SELL
              (required)
            - horizon: execution window in SECONDS, e.g. 3600 (required)
            - start_time: e.g. "09:30:00" (optional, defaults to market open)

            For CSS (custom static schedule), one of:

            - type: "css" (required)
            - orders: dict mapping timestamps to quantities, or
            - rows (ABM only): a list of individual orders, each a dict with
              ``time`` (exchange-local, to the millisecond), ``ref`` (unique
              per order; no "," or "#"), ``order_type`` ("market", "limit",
              "ioc", "cancel", "stop", "stop_limit" or "amend"), ``side``
              ("buy"/"sell") and ``size`` (lots). Optional: ``price_ref``
              ("near", "far" or "mid") and ``offset_ticks`` (positive = less
              aggressive), ``peg``, ``peg_limit_ticks``, ``peak``,
              ``peak_random_pct``, ``lifetime_s``, ``stop_offset_ticks``.
              ``peg_limit_ticks`` (>= 0, pegged limit orders only) gives a peg
              a limit: its reference when entered, moved that many ticks in
              the aggressive direction. While the reference is past the limit
              the order is pulled; it comes back at the back of the queue, as
              ``<ref>#<n>``, when the reference returns (LSE MIT201 6.1).
              A ``cancel`` row names an earlier ``ref``. An ``amend`` row
              names an earlier limit or stop_limit ``ref`` that no earlier
              row cancels, and gives a new price (``price_ref`` and
              ``offset_ticks``, priced at the amend time), a new remaining
              visible ``size``, or both. A price change loses queue
              priority, a size change alone keeps it, and an amend of an
              order that has already filled or been cancelled does nothing.
              A price amend of a pegged order is a 422. A ``ref`` of the form
              ``<role>-<n>`` (e.g. "spoof-3") names the order's role for
              :meth:`get_sim_events`. Or
            - rows_csv (ABM only): the same rows as CSV, given as CSV text,
              a path to a ``.csv`` file (str or ``pathlib.Path``), or a
              pandas / polars DataFrame; the SDK sends CSV text. The header
              names the columns used (the row keys above, any order); an
              empty cell is a field not set; ``peg`` is 0/1/true/false.
              Errors name the CSV line (header = line 1) and column, and the
              run's schedule report (:meth:`get_sim_schedule_report`) refers
              to the same lines. Give ``rows`` or ``rows_csv``, not both.

            An FM job accepts at most one algo and needs a real market day —
            a testdata run cannot carry one.
        model_id : str, optional
            FM only, required when ``engine="fm"``. A ``model_id`` or a
            ``production_name`` (e.g. "flow-hkex-1-100M") from
            :meth:`~simudyne.resources.fm.FmResource.models`. Names match
            ignoring case, spaces, underscores and dashes; the production name
            is tried first. The job runs under the resolved ``model_id``.
        duration_minutes : float, optional
            FM only. Sim horizon as wall-clock minutes, measured from the first
            row of the warm-start context. The resulting frame count is
            reported in the run's output rather than requested up front — an
            illiquid symbol simply produces fewer frames for the same duration.
            A duration running past the close is clipped.
        horizon : int, optional
            FM only. A raw frame count; the older form of ``duration_minutes``
            and applied only when that is unset.
        device : {'cpu', 'gpu', ''}, default ''
            FM only. Overrides the model's declared default compute.
        model_args : dict, optional
            FM only. Per-run overrides of the model's declared knobs, e.g.
            ``{"temperature": 0.7}``. Unknown or out-of-range keys are
            rejected.

        Returns
        -------
        dict
            Submission result containing:

            - job_id (str): unique job identifier, passed to
              :meth:`get_job_status` and :meth:`get_job_results`
            - sim_ids (list of str): the simulation ids that will be run, one
              per Monte Carlo run, known at submission for both engines
            - n_runs (int): number of runs queued
            - engine (str): the engine that accepted the job

        Raises
        ------
        PulseAPIError
            If the key is not pro or demo tier (403).

            If the request itself is malformed (422): ``provider`` or
            ``exchange`` is not a recognised value; ``n_runs`` is below 1, or
            above 8 with ``engine="fm"``; ``engine="fm"`` without
            ``model_id``; or an ``exec_algos`` entry has a ``start_time``
            that is not "HH:MM" / "HH:MM:SS" or a ``side`` that is not "buy"
            or "sell".

            If the named data is unusable (422). The market identity is checked
            against the catalogue before submission:

            - ``engine="abm"`` — all four market fields are required, and the
              day must be calibrated. The error names the dates that *are*
              calibrated for that symbol and points at
              :meth:`~simudyne.resources.data.DataResource.calibrate`.
            - ``engine="fm"`` — the four fields are all-or-nothing. Set none of
              them and the run uses the model image's baked-in test day. Set
              all four and the day must exist in the data registry and the
              model must accept that market; the error names the model's
              supported markets and the dates that do exist. Set *some* of
              them and the request is refused, naming exactly which are
              missing — a partial identity is always a mistake, never a
              request for test data.

            If a field does not belong to the chosen engine (422), e.g.
            ``scenario`` with ``engine="fm"`` or ``model_id`` with
            ``engine="abm"``. Every field you set is sent, so the API — not
            the SDK — decides, and a misplaced field is never silently
            dropped.

            If ``scenario_params`` fails validation (422).

            If ``model_id`` matches more than one model (400) or none (404).

            If a backing service cannot be reached: the model registry
            (pulse-orchestrator) for an FM run or for resolving ``model_id``
            (502), or the simulation service (503). A 503 is retried
            automatically; a 502 is not, because the job may already have
            been queued — check :meth:`get_jobs` before submitting again.

        See Also
        --------
        get_job_status : Poll a submitted job, either engine.
        get_job_results : Read results once the job completes.
        simudyne.resources.data.DataResource.available_data : Days an FM can be
            prompted with.
        simudyne.resources.data.DataResource.calibrated_data : Days the ABM can
            simulate.
        simudyne.resources.fm.FmResource.models : Models and what each accepts.

        Examples
        --------
        An agent-based run:

        >>> job = client.simulation.run(
        ...     symbol="700.HK", cal_date="2025-09-02",
        ...     provider="omd", exchange="hkex_securities",
        ...     n_runs=10, scenario="flash_crash",
        ... )

        The same market through a foundation model — only ``engine`` and
        ``model_id`` change:

        >>> job = client.simulation.run(
        ...     symbol="700", cal_date="2025-09-01",
        ...     provider="bmll", exchange="hkex_securities",
        ...     engine="fm", model_id="flow-hkex-1-100M", duration_minutes=30,
        ... )

        A smoke test against the model's baked-in day — no market named at all:

        >>> job = client.simulation.run(engine="fm", model_id="flow-hkex-1-100M")

        An execution algorithm, on either engine:

        >>> job = client.simulation.run(
        ...     symbol="700.HK", cal_date="2025-09-02",
        ...     provider="omd", exchange="hkex_securities",
        ...     n_runs=20,
        ...     exec_algos=[{
        ...         "type": "twap",
        ...         "order_size": -500,  # lots; negative = buy
        ...         "horizon": 3600,
        ...     }],
        ... )

        A schedule of individual orders as CSV (text, a .csv path or a
        DataFrame):

        >>> schedule = (
        ...     "time,ref,order_type,side,size,price_ref,offset_ticks,lifetime_s\n"
        ...     "2025-09-02 10:00:00.000,spoof-1,limit,buy,5000,near,2,4\n"
        ...     "2025-09-02 10:00:01.500,genuine-1,market,sell,200,,,\n"
        ... )
        >>> job = client.simulation.run(
        ...     symbol="700.HK", cal_date="2025-09-02",
        ...     provider="omd", exchange="hkex_securities",
        ...     exec_algos=[{"type": "css", "rows_csv": schedule}],
        ... )
        >>> job = client.simulation.run(
        ...     symbol="700.HK", cal_date="2025-09-02",
        ...     provider="omd", exchange="hkex_securities",
        ...     exec_algos=[{"type": "css", "rows_csv": "my_schedule.csv"}],
        ... )

        Both engines are polled and read identically:

        >>> import time
        >>> while not client.simulation.get_job_status(job["job_id"])["is_complete"]:
        ...     time.sleep(20)
        >>> book = client.simulation.get_sim_data(job["sim_ids"][0])
        """
        payload = {"engine": engine, "seed": seed}

        # The market identity is all-or-nothing on an FM run: sending a blank
        # field is not the same as omitting it, since some-but-not-all is an
        # error and none of them is the model's baked-in test day.
        for name, value in (
            ("symbol", symbol), ("cal_date", cal_date),
            ("provider", provider), ("exchange", exchange),
        ):
            if value:
                payload[name] = value

        if n_runs is not None:
            payload["n_runs"] = n_runs
        if exec_algos:
            payload["exec_algos"] = self._serialize_exec_algos(exec_algos)

        # Engine-specific fields are sent whenever the caller set them, on
        # either engine. The API rejects a field that belongs to the other
        # engine; dropping it here instead would run the job without the
        # caller's input and say nothing. Unset defaults are never sent, so a
        # plain run of either kind carries no stray fields.
        if scenario is not None:
            payload["scenario"] = scenario
        if scenario_params is not None:
            payload["scenario_params"] = scenario_params
        if model_id:
            payload["model_id"] = model_id
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if horizon is not None:
            payload["horizon"] = horizon
        if device:
            payload["device"] = device
        if model_args is not None:
            payload["model_args"] = model_args

        return self._pro_request("POST", RUN_PATH, json=payload)

    @staticmethod
    def _serialize_exec_algos(exec_algos: list) -> list:
        """Make CSS configs JSON: pd.Series ``orders`` become dicts and
        ``rows_csv`` (a path or a DataFrame) becomes CSV text."""
        result = []
        for algo in exec_algos:
            algo = dict(algo)
            if algo.get("type") == "css" and "orders" in algo:
                orders = algo["orders"]
                if hasattr(orders, "items"):
                    algo["orders"] = {str(k): int(v) for k, v in orders.items()}
            if "rows_csv" in algo:
                algo["rows_csv"] = _csv_text(algo["rows_csv"])
            result.append(algo)
        return result

    def get_jobs(self, limit: int = 100, offset: int = 0):
        """Get simulation jobs submitted by the authenticated user, newest first.

        Returns a list of jobs with their associated simulation IDs. Use this
        to find job IDs for past runs or to see what simulations are pending.

        Parameters
        ----------
        limit : int, default 100
            Max jobs to return, 1 to 500.
        offset : int, default 0
            Jobs to skip, for paging with ``limit``.

        Returns
        -------
        dict
            Listing containing:

            - jobs (list of dict): one per job, each with ``job_id`` (str),
              ``sim_ids`` (list of str) and ``created_at`` (str)
            - total (int): total number of jobs on the account
            - limit (int), offset (int): the page that was returned

        Raises
        ------
        PulseAPIError
            If the key is not pro or demo tier (403), or ``limit`` or ``offset`` is
            out of range (422).

        See Also
        --------
        get_job_status : Poll one job.
        get_job_results : Read one job's results.

        Examples
        --------
        >>> result = client.simulation.get_jobs()
        >>> print(f"You have {result['total']} jobs")
        >>> for job in result["jobs"]:
        ...     print(f"Job {job['job_id']}: {len(job['sim_ids'])} simulations")
        ...     print(f"  Created: {job['created_at']}")

        The most recent job, and its results:

        >>> jobs = client.simulation.get_jobs(limit=1)["jobs"]
        >>> latest = jobs[0]
        >>> results = client.simulation.get_job_results(latest["job_id"])
        """
        return self._pro_request(
            "GET", JOBS_PATH, params={"limit": limit, "offset": offset}
        )

    def get_job_status(self, job_id: str):
        """Get the status of all simulations in a job.

        Use this to track simulation progress, for either engine. Poll on
        ``is_complete`` rather than on individual status strings.

        Parameters
        ----------
        job_id : str
            The job ID from run() or get_jobs()

        Returns
        -------
        dict
            Job status containing:

            - job_id (str): the job identifier
            - engine (str): "abm" or "fm"
            - total_simulations (int): number of simulations in the job
            - status_summary (dict): count by status, e.g.
              ``{"running": 2, "completed": 8}``
            - is_complete (bool): True once every simulation has finished
            - has_errors (bool): True if any simulation failed
            - simulations (list of dict): per-simulation status, each with
              ``sim_id`` (str), ``status`` (str), ``error_message`` (str),
              ``symbol_id`` (str) and ``timestamp`` (str). A finished run is
              "complete" (older jobs: "completed"), a failed one "error" or
              "failed"; anything else is still in flight.
            - status, message, detail (str): FM jobs only, the inference
              pod's own state, e.g. waiting for a GPU. Present only when the
              orchestrator reports them.

        Raises
        ------
        PulseAPIError
            If ``job_id`` is unknown or belongs to another account (404), or
            the key is not pro or demo tier (403).

        See Also
        --------
        run : Submit a job.
        get_job_results : Read results once the job completes.
        get_job_logs : The run log, for a job that failed.

        Notes
        -----
        ``is_complete`` and ``has_errors`` are independent: a job where some
        runs failed and the rest finished reports both as True. Poll on
        ``is_complete`` and inspect ``has_errors`` afterwards, rather than
        treating an error as the end of the job.

        Examples
        --------
        Check whether a job has finished:

        >>> status = client.simulation.get_job_status("2103533f15ab0893")
        >>> if status["is_complete"]:
        ...     print("All simulations finished")
        ... else:
        ...     print(f"Progress: {status['status_summary']}")

        Poll to completion:

        >>> import time
        >>> result = client.simulation.run(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ...     n_runs=10,
        ... )
        >>> job_id = result["job_id"]
        >>> while True:
        ...     status = client.simulation.get_job_status(job_id)
        ...     print(f"Status: {status['status_summary']}")
        ...     if status["is_complete"]:
        ...         break
        ...     time.sleep(30)
        >>> if status["has_errors"]:
        ...     failed = [
        ...         s for s in status["simulations"]
        ...         if s["status"] in ("error", "failed")
        ...     ]
        ...     for sim in failed:
        ...         print(sim["sim_id"], sim["error_message"])
        """
        return self._pro_request("GET", f"{JOBS_PATH}/{job_id}/status")
    
    @staticmethod
    def list_scenarios():
        """List available market scenarios and their descriptions.

        Returns
        -------
        dict
            Scenario names mapped to their descriptions. A copy, so mutating
            it does not affect later calls.

        See Also
        --------
        get_scenario_defaults : The default parameters for one scenario.

        Notes
        -----
        Served from a constant in the SDK rather than from the API, so it
        needs no key, costs no request, and reflects the scenarios this SDK
        version knows about.

        Examples
        --------
        >>> scenarios = client.simulation.list_scenarios()
        >>> for name, desc in scenarios.items():
        ...     print(f"{name}: {desc}")

        >>> sorted(client.simulation.list_scenarios())
        ['buy_panic', 'flash_crash', 'gradual_selloff', 'normal', ...]
        """
        return SCENARIOS.copy()
    
    @staticmethod
    def get_scenario_defaults(scenario: str):
        """Get default parameters for a scenario.

        Parameters
        ----------
        scenario : str
            Scenario name (e.g., "flash_crash")

        Returns
        -------
        dict
            Default parameter values for the scenario. Empty for ``"normal"``,
            which injects nothing, and for any unknown name. A copy, so
            mutating it does not affect later calls.

        See Also
        --------
        list_scenarios : Every scenario this SDK version knows about.

        Notes
        -----
        Served from a constant in the SDK rather than from the API, so it
        needs no key and costs no request. An unknown scenario returns ``{}``
        rather than raising — check against :meth:`list_scenarios` if you need
        to tell "no defaults" from "no such scenario".

        Examples
        --------
        >>> defaults = client.simulation.get_scenario_defaults("flash_crash")
        >>> print(defaults)
        {'impact_multiplier': 150.0, 'order_size_ratio': 0.02, ...}

        Override one default and keep the rest:

        >>> params = client.simulation.get_scenario_defaults("flash_crash")
        >>> params["start_time"] = "11:00:00"
        >>> client.simulation.run(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ...     scenario="flash_crash",
        ...     scenario_params=params,
        ... )
        """
        return SCENARIO_DEFAULTS.get(scenario, {}).copy()

    def get_job_results(self, job_id: str):
        """Get aggregated results for all simulations in a job.

        Returns params, metrics, and available files for each completed simulation.

        Parameters
        ----------
        job_id : str
            The job ID from run() or get_jobs()

        Returns
        -------
        dict
            Aggregated results containing:

            - job_id (str): the job identifier
            - total_simulations (int): total simulations in the job
            - completed (int): how many have finished
            - simulations (list of dict): per-simulation results, each with
              ``sim_id`` (str), ``status`` (str), ``available_files`` (list of
              str), ``params`` (dict) and ``metrics`` (dict). A simulation
              whose results could not be read carries ``error`` (str) instead.

        Raises
        ------
        PulseAPIError
            If ``job_id`` is unknown or belongs to another account (404), or
            the key is not pro or demo tier (403).

        See Also
        --------
        get_sim_data : The generated book for one simulation.
        get_job_status : Poll a job without pulling its metrics.

        Notes
        -----
        Safe to call before the job finishes — incomplete simulations appear
        with their current ``status`` and no metrics, so ``completed`` against
        ``total_simulations`` is a progress reading in its own right.

        Examples
        --------
        >>> job_id = client.simulation.get_jobs(limit=1)["jobs"][0]["job_id"]
        >>> results = client.simulation.get_job_results(job_id)
        >>> for sim in results["simulations"]:
        ...     if sim["status"] in ("complete", "completed"):
        ...         print(f"{sim['sim_id']}: {sim['metrics']}")

        Pull the book for every simulation that finished:

        >>> frames = [
        ...     client.simulation.get_sim_data(sim["sim_id"])
        ...     for sim in results["simulations"]
        ...     if sim["status"] in ("complete", "completed")
        ... ]
        """
        return self._pro_request("GET", f"{JOBS_PATH}/{job_id}/results")

    def get_job_logs(self, job_id: str) -> str:
        """Fetch the engine run log for one of your jobs, as plain text.

        The worker writes a diagnostic log per job — this is the thing to read
        when a run fails or finishes with nothing plottable, and the thing to
        attach when sending a problem to support@simudyne.com.

        Parameters
        ----------
        job_id : str
            The job ID from run() or get_jobs()

        Returns
        -------
        str
            The log text.

        Raises
        ------
        PulseAPIError
            404 when the job does not exist, is not yours, or
            wrote no log; 403 if the key is not pro or demo tier.

        See Also
        --------
        get_job_status : Where the job has got to.

        Examples
        --------
        >>> job_id = client.simulation.get_jobs(limit=1)["jobs"][0]["job_id"]
        >>> status = client.simulation.get_job_status(job_id)
        >>> if status["has_errors"]:
        ...     print(client.simulation.get_job_logs(job_id)[:2000])
        """
        # Plain text, not JSON — go through the retrying transport directly.
        url = f"{self._client.base_url}{JOBS_PATH}/{job_id}/logs"
        response = self._client._request_with_retries("GET", url)
        return response.text

    def run_lrm(
        self,
        symbol: str,
        cal_date: str,
        provider: str,
        exchange: str,
        order_sizes: list,
        n_runs: int = 50,
        seed: int = 42,
        horizon_mins: int = 60,
        strategy: str = "vwap",
        side: str = None,
        start_time: str | None = None,
        scenario: str | None = None,
        scenario_params: dict | None = None,
    ):
        """Run a liquidity-risk grid: market impact across a ladder of order sizes.

        One execution algo is built per entry in order_sizes, and all of them
        share a single baseline, so the cost is ``n_runs * (1 + len(order_sizes))``
        simulations rather than one baseline per size. Poll the returned job_id
        through the usual job endpoints.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "700")
        cal_date : str
            Calibration date in YYYY-MM-DD format
        provider : str
            Data provider (e.g. "omd", "bmll")
        exchange : str
            Exchange protocol (e.g. "hkex_securities")
        order_sizes : list
            Order sizes in LOTS — one algo per entry
        n_runs : int, default 50
            Monte Carlo runs per arm (default 50)
        seed : int, default 42
            Random seed (default 42)
        horizon_mins : int, default 60
            Execution horizon in minutes (default 60)
        strategy : str, default 'vwap'
            "vwap" or "twap" (default "vwap")
        side : str, optional
            "buy" or "sell"; defaults to the sign of each order size
        start_time : str, optional
            When the algos start, "HH:MM"; defaults to the market open.
        scenario : str, optional
            Market scenario every arm runs under, as on :meth:`run`; the
            API's default is "normal".
        scenario_params : dict, optional
            Overrides for ``scenario``, validated as on :meth:`run`.

        Returns
        -------
        dict
            job_id : str
                Pass to :meth:`get_job_status` and :meth:`get_job_results`.
            order_sizes : list of int
                The ladder as submitted.
            n_runs : int
                Monte Carlo runs per arm.
            total_jobs : int
                Simulations queued, ``n_runs * (1 + len(order_sizes))``.

            No ``sim_ids`` are returned; read them from
            :meth:`get_job_status` once the job is queued.

        Raises
        ------
        PulseAPIError
            If the key is not pro or demo tier (403). If ``order_sizes`` is
            empty or contains 0, ``strategy`` is not "vwap" or "twap",
            ``side`` is not "buy" or "sell", ``provider`` or ``exchange`` is
            not a recognised value, ``scenario_params`` fails validation, or
            the symbol-day has not been calibrated (422). If the simulation
            service is unreachable (503).

        See Also
        --------
        run : A single run, with any execution algos.
        get_job_status : Poll the submitted job.
        get_job_results : Read per-size results once complete.

        Notes
        -----
        ``order_sizes`` is in **lots**, as is ``order_size`` on :meth:`run`,
        and signed the same way: negative buys, positive sells, and 0 is
        rejected. Passing ``side`` overrides the sign for every entry and
        only each size's magnitude is used.

        Examples
        --------
        A five-rung ladder, costing ``50 * (1 + 5)`` = 300 simulations:

        >>> job = client.simulation.run_lrm(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ...     order_sizes=[10, 50, 100, 500, 1000],
        ... )
        >>> job["job_id"]
        '2103533f15ab0893'

        A TWAP ladder on the buy side over half an hour, with fewer runs per
        arm:

        >>> job = client.simulation.run_lrm(
        ...     symbol="700.HK",
        ...     cal_date="2025-09-02",
        ...     provider="omd",
        ...     exchange="hkex_securities",
        ...     order_sizes=[100, 200, 400],
        ...     strategy="twap",
        ...     side="buy",
        ...     horizon_mins=30,
        ...     n_runs=20,
        ... )

        Results come back through the usual job endpoints:

        >>> results = client.simulation.get_job_results(job["job_id"])
        """
        payload = {
            "symbol": symbol,
            "cal_date": cal_date,
            "provider": provider,
            "exchange": exchange,
            "order_sizes": order_sizes,
            "n_runs": n_runs,
            "seed": seed,
            "horizon_mins": horizon_mins,
            "strategy": strategy,
        }
        for name, value in (
            ("side", side), ("start_time", start_time),
            ("scenario", scenario), ("scenario_params", scenario_params),
        ):
            if value is not None:
                payload[name] = value
        return self._pro_request("POST", LRM_PATH, json=payload)

    def list_sim_files(self, sim_id: str):
        """List available files for a specific simulation.

        Parameters
        ----------
        sim_id : str
            The simulation ID

        Returns
        -------
        dict
            Contains:
            - sim_id (str): The simulation identifier
            - files (list): List of available filenames
            - has_sim_data (bool): Whether sim_data.parquet exists
            - has_params (bool): Whether params.json exists
            - has_results (bool): Whether results.json exists
            - has_mid_price (bool): Whether mid_price_by_min.parquet exists
            - has_l2_by_second (bool): Whether l2_by_second.parquet exists
            - has_exec_schedule (bool): Whether exec_schedule.parquet exists
            - has_schedule_by_min (bool): Whether schedule_by_min.parquet exists
            - has_exec_results (bool): Whether exec_results.parquet exists
            - has_schedule_report (bool): Whether schedule_report.parquet
              exists (runs with an order schedule; see
              :meth:`get_sim_schedule_report`)

        Raises
        ------
        PulseAPIError
            If ``sim_id`` is unknown, or belongs to another account and is
            not part of the shared cached library — status 404. Cached
            baseline simulations (see :meth:`list_cached`) are readable by
            every account.

        See Also
        --------
        get_sim_data : Download one of the listed files.
        get_sim_params : The parameters the run used.
        get_sim_metrics : The run's summary metrics.

        Examples
        --------
        >>> sim_id = client.simulation.list_cached(symbol="700.HK")["simulations"][0]["example_sim_id"]
        >>> files = client.simulation.list_sim_files(sim_id)
        >>> print(f"Available: {files['files']}")

        The ``has_*`` flags are the cheap way to check before fetching, since
        which files exist depends on what the run was configured to emit:

        >>> if files["has_exec_schedule"]:
        ...     schedule = client.simulation.get_sim_data(
        ...         sim_id, filename="exec_schedule.parquet"
        ...     )
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/files")

    def get_sim_params(self, sim_id: str):
        """Get simulation parameters for a specific simulation.

        Parameters
        ----------
        sim_id : str
            The simulation ID

        Returns
        -------
        dict
            Simulation parameters including:
            - sim_id (str)
            - calibration_params (dict)
            - scenario_params (dict)
            - exec_algo_params (dict)
            - sim_params (dict)

        Raises
        ------
        PulseAPIError
            If ``sim_id`` is unknown or belongs to another account — status
            404.

        See Also
        --------
        get_sim_metrics : The run's summary metrics.
        list_sim_files : Every file the run produced.

        Examples
        --------
        >>> sim_id = client.simulation.list_cached(symbol="700.HK")["simulations"][0]["example_sim_id"]
        >>> params = client.simulation.get_sim_params(sim_id)
        >>> scenario = params["scenario_params"]
        >>> print(f"Scenario: {scenario['scenario_name']}")

        Recover exactly what a past run was given, to reproduce it:

        >>> sim_params = params["sim_params"]
        >>> sim_params["seed"]
        42
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/params")

    def get_sim_metrics(self, sim_id: str):
        """Get result metrics for a specific simulation.

        Parameters
        ----------
        sim_id : str
            The simulation ID

        Returns
        -------
        dict
            Result metrics for the simulation — summary statistics computed by
            the engine, such as realised spread and volume.

        Raises
        ------
        PulseAPIError
            If ``sim_id`` is unknown, belongs to another account, or the
            simulation has not finished and so wrote no metrics — status 404.

        See Also
        --------
        get_sim_params : The parameters the run used.
        list_sim_files : Every file the run produced.

        Examples
        --------
        >>> sim_id = client.simulation.list_cached(symbol="700.HK")["simulations"][0]["example_sim_id"]
        >>> metrics = client.simulation.get_sim_metrics(sim_id)
        >>> print(metrics)

        Compare one metric across every run in a job:

        >>> job_id = client.simulation.get_jobs(limit=1)["jobs"][0]["job_id"]
        >>> status = client.simulation.get_job_status(job_id)
        >>> for sim in status["simulations"]:
        ...     if sim["status"] in ("complete", "completed"):
        ...         m = client.simulation.get_sim_metrics(sim["sim_id"])
        ...         print(sim["sim_id"], m.get("mean_spread"))
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/metrics")

    def get_sim_events(self, sim_id: str):
        """Market-quality events and source-backed manipulation patterns in one run.

        Runs the same event detector the platform uses on real market data
        over this run's order book. Computed on first request, then cached.

        Types that run on any data: market quality (``liquidity_withdrawal``,
        ``spread_blowout``, ``price_jump``, ``volume_burst``, ``cliff``,
        ``auction``) and manipulation (``spoofing_like``, ``layering``,
        ``quote_stuffing``, ``ping_orders``, ``advancing_bid``,
        ``momentum_ignition``, ``smoking``, ``marking_close``,
        ``auction_cancel``). Simulation only, because they need the account:
        ``wash_trade`` and ``painting_tape``, plus the account form of
        ``marking_close`` (``features["form"] == "account"``). The account is
        the run's own scheduled orders, and these rules need the aggressor of
        each trade (``aggressor_order_id`` on newer runs' TRADE rows); an
        older run gets none of them.

        Parameters
        ----------
        sim_id : str
            The simulation ID (an agent-based run; foundation-model runs have
            no order lifecycle to scan).

        Returns
        -------
        dict
            ``{"sim_id", "symbol", "date", "detector_version", "stats",
            "events": [...]}``. Each event has:

            - event_id (str): pass to :meth:`get_sim_event`
            - type (str), side (str or None: "bid"/"ask", "buy"/"sell" for
              marking_close, "up"/"down" for price moves)
            - ts, ts_end, duration_ms, severity (0-100), score,
              severity_basis
            - features (dict): the type's measurements
            - checks (list of dict): every rule applied, each ``{label,
              value, rule, passed, basis, source}``; ``basis`` is "doc" (a
              qualifying source states the figure: legislation, official
              guidance, a final enforcement finding, or a peer-reviewed
              article in its published version), "default" (Pulse's
              calibration, including figures derived from a source) or
              None for context rows, ``source`` a short citation
            - order_ids (list of str): for an order-level type
              (spoofing_like, layering, ping_orders, advancing_bid, smoking,
              auction_cancel, wash_trade, painting_tape) the orders behind
              the event; for a window-level type (quote_stuffing,
              momentum_ignition, marking_close) the base refs of the
              scheduled orders placed inside [ts, ts_end]
            - thumb: a small normalised picture

            An order from a schedule (``css`` with ``rows``) keeps its row's
            ``ref`` as its id, with ``#<k>`` added for an iceberg's later
            peaks and a limited peg's re-entries. A ref is ``<role>-<n>``;
            the role (spoof, layer, stuff, probe, advance, ignite, smoke,
            close, wash, paint; anything else is genuine) names the type the
            order was planted for, and a planted order is caught when an
            event of that type lists its base ref (a layer is also caught by
            spoofing_like).

        Raises
        ------
        PulseAPIError
            404 if ``sim_id`` is unknown or the run wrote no order book; 422
            for a foundation-model run.

        See Also
        --------
        get_sim_event : One event with its full signature picture.
        get_sim_schedule_orders : The schedule's orders and the rules of
            their roles measured on each.

        Examples
        --------
        >>> events = client.simulation.get_sim_events(sim_id)["events"]
        >>> spoofs = [e for e in events if e["type"] == "spoofing_like"]
        >>> caught = {i.split("#")[0] for e in spoofs for i in e["order_ids"]}
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/events")

    def get_sim_event(self, sim_id: str, event_id: str):
        """One event from :meth:`get_sim_events`, with its full signature picture.

        The same fields as an event in :meth:`get_sim_events`, plus
        ``signature``: a normalised depth picture around the event with
        spread, imbalance and activity traces.
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/events/{event_id}")

    def get_sim_schedule_orders(self, sim_id: str):
        """Every order a schedule placed in one run, and how it measured
        against the rules of its role.

        Orders are the ones a ``css`` schedule with ``rows`` placed, found by
        their ``ref`` (iceberg peaks and a limited peg's re-entries,
        ``<ref>#<k>``, are folded into one order). Genuine orders are listed
        too. A planted order that :meth:`get_sim_events` did not catch says
        here which rule it failed. Computed with the events, then cached.

        Parameters
        ----------
        sim_id : str
            The simulation ID (an agent-based run).

        Returns
        -------
        dict
            ``{"thresholds", "orders"}``.

            - thresholds (dict): the run's ``median_size``,
              ``size_quantile``, ``size_floor``, ``small_size``, ``tick``,
              ``aggressor_ids`` (whether the run records the aggressor of
              each trade) and each role's parameters (``spoof``, ``layer``,
              ``probe``, ``advance``, ``smoke``, ``wash``, ``paint``)
            - orders (list of dict), each:

              - ref (str), role (str): genuine, spoof, layer, stuff, probe,
                advance, ignite, smoke, close, wash or paint
              - side (str): "bid" or "ask"
              - t_place, t_end, end: placed, and filled or cancelled;
                ``end`` is "filled", "cancelled" or "open". An order that
                filled on arrival is placed at its first fill.
              - price, size, filled, peaks
              - ticks_behind_touch, ticks_from_mid: where it rested when
                placed
              - tested_against (str or None): the event type its role is
                planted for; None for genuine
              - rules (dict): ``{rule_key: {label, value, need, passed,
                basis, source}}``, that type's rules measured on the order;
                empty for genuine orders and the window-level roles stuff,
                ignite and close. On a run without aggressor ids, wash and
                paint orders carry one rule, ``aggressor_ids``.
              - meets_rules (bool or None): whether every rule passed; None
                where ``rules`` is empty or the run has no aggressor ids
              - amends (list of dict): ``{t, price, size}`` per amend the
                schedule made to it

        Raises
        ------
        PulseAPIError
            404 if ``sim_id`` is unknown or the run wrote no order book; 422
            for a foundation-model run.

        See Also
        --------
        get_sim_events : The events that caught (or missed) these orders.

        Examples
        --------
        >>> report = client.simulation.get_sim_schedule_orders(sim_id)
        >>> for o in report["orders"]:
        ...     if o["role"] == "spoof" and o["meets_rules"] is False:
        ...         print(o["ref"], [r["label"] for r in o["rules"].values() if not r["passed"]])
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/schedule-orders")

    def get_sim_schedule_report(self, sim_id: str) -> list:
        """The run's schedule report: what happened to each order schedule row.

        One row per schedule row, written by the engine: whether the row was
        released or skipped as invalid (and why), when and where it was
        placed, and how it ended. The same data as
        ``get_sim_data(sim_id, "schedule_report.parquet")``, as plain dicts.

        Parameters
        ----------
        sim_id : str
            The simulation ID (an agent-based run with an order schedule).

        Returns
        -------
        list of dict
            One dict per schedule row, in time order (rows with the same
            time keep their file order), with these keys:

            - line (int): 1-based CSV line, header = 1 (for rows given
              inline, the row index)
            - ref (str): the row's ORDER_ID
            - ord_type (str): Limit, Market, IOC, Cancel, Stop, StopLimit or
              Amend
            - side (str): Buy or Sell
            - symbol (str)
            - t_scheduled (str): exchange-local ISO time with ms
            - t_placed (str): ISO time, empty if never placed
            - price_placed (float or None): price units; None for market
              orders and orders never placed
            - size (int): visible size
            - total_size (int)
            - engine_ids (str): ";"-joined engine order ids (ref, ref#2, ...)
            - amends (int): amends applied
            - repegs (int)
            - filled_qty (int), avg_fill_price (float or None),
              n_fills (int): from the trader's own execution reports
            - end (str): "filled", "cancelled", "expired", "open_at_close",
              "not_placed", "applied" (amend/cancel rows) or "skipped"
            - end_reason (str): "lifetime", "cancel_row",
              "cancel_on_fill:<target ref>", "peg_limit", "end_of_day",
              "no_valid_book", "outside_hours", "run_ended", "elected" (a stop
              elected; its child order's outcome is on the same row) or "";
              for a skipped row (end "skipped") the reason text, e.g.
              "column PEG_LIMIT: applies only to pegged Limit orders"
            - t_end (str): ISO time, empty if none

        Raises
        ------
        PulseAPIError
            404 if ``sim_id`` is unknown, or the run has no report (it had no
            schedule, or it predates the report).

        See Also
        --------
        get_sim_data : ``exec_results.parquet`` counts the skipped rows
            (``schedule_rows_skipped``, ``schedule_skip_reasons``).
        get_job_logs : The engine log, with a line per skipped row.

        Examples
        --------
        >>> rows = client.simulation.get_sim_schedule_report(sim_id)
        >>> for r in rows:
        ...     if r["end"] == "skipped":
        ...         print(r["line"], r["ref"], r["end_reason"])
        """
        report = self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/schedule-report")
        return report.get("rows", []) if isinstance(report, dict) else report

    def get_sim_data(self, sim_id: str, filename: str = "sim_data.parquet"):
        """Download simulation data as a Polars DataFrame.

        Free-tier quota: downloading from a cached simulation group you haven't
        downloaded before consumes one unit of the daily allowance (HTTP 429
        once exhausted). Groups you've already downloaded — via this method,
        the bulk ZIP, or the web explorer — stay free forever, any run or file
        format. Your own job runs are never charged. See
        ``client.profile.downloads()``.

        Parameters
        ----------
        sim_id : str
            The simulation ID
        filename : str, default 'sim_data.parquet'
            File to download. One of:

            - "sim_data.parquet": full simulation output (LOB + orders)
            - "mid_price_by_min.parquet": mid-price by minute
            - "l2_by_second.parquet": L2 order book, 10 levels, per second
            - "exec_schedule.parquet": execution schedule, if an algo ran
            - "schedule_by_min.parquet": algo schedule by minute, if an algo ran
            - "exec_results.parquet": execution cost metrics, if an algo ran.
              One row; besides the cost columns it carries
              ``schedule_rows_skipped`` (int, order schedule rows the engine
              skipped as invalid, 0 if none) and ``schedule_skip_reasons``
              (str, up to 5 reasons joined with " | ", "+N more" if more).
              Runs that predate these columns do not have them: read them as
              0 and "". :meth:`get_job_logs` has every skipped line.
            - "schedule_report.parquet": one row per order schedule row, if
              the run had a schedule (see :meth:`get_sim_schedule_report`)

        Returns
        -------
        polars.DataFrame
            The simulation data.

        Raises
        ------
        PulseAPIError
            If ``filename`` is not one of the seven names above (400);
            ``sim_id`` is unknown, or the file was not written by this run
            (404); or the free-tier download allowance is exhausted (429,
            raised at once: the allowance rolls over in hours, not seconds).

        See Also
        --------
        list_sim_files : Which files a given simulation actually wrote.
        get_bulk_data : The same files for many simulations, as one ZIP.

        Examples
        --------
        >>> sim_id = client.simulation.list_cached(symbol="700.HK")["simulations"][0]["example_sim_id"]
        >>> df = client.simulation.get_sim_data(sim_id)
        >>> print(df.shape)
        >>> print(df.head())

        Mid-price by minute, which is far smaller than the full book:

        >>> mid_df = client.simulation.get_sim_data(sim_id, "mid_price_by_min.parquet")

        Check before fetching a file that only exists when an algo ran:

        >>> files = client.simulation.list_sim_files(sim_id)
        >>> if files["has_exec_schedule"]:
        ...     sched = client.simulation.get_sim_data(sim_id, "exec_schedule.parquet")
        """
        import polars as pl
        
        url = f"{self._client.base_url}{RESULTS_PATH}/{sim_id}/data/{filename}"
        # Through the client, for its timeout, retries and error handling.
        response = self._client._request_with_retries("GET", url)

        return pl.read_parquet(io.BytesIO(response.content))

    def list_cached(
        self,
        symbol: str = None,
        date: str = None,
        scenario: str = None,
    ):
        """List cached baseline simulations available to free tier users.

        Returns aggregated simulation metadata for baseline (non-exec algo) simulations.
        Use the returned sim_id to retrieve data via get_sim_data(), get_sim_params(), etc.

        Free tier users can only access baseline simulations - no execution algorithms.

        Parameters
        ----------
        symbol : str, optional
            Filter by symbol (e.g., "700.HK", "9999.HK")
        date : str, optional
            Filter by date (e.g., "2025-09-02")
        scenario : str, optional
            Filter by scenario (e.g., "normal", "flash_crash")

        Returns
        -------
        dict
            Contains:
            - simulations (list): List of cached simulation groups, each with:
            - example_sim_id (str): A sim_id from this group (use with get_sim_data)
            - provider (str): Data provider, e.g. "omd"
            - exchange (str): Exchange protocol, e.g. "hkex_securities"
            - symbol (str): Trading symbol
            - date (str): Calibration date
            - scenario (str): Scenario name
            - n_runs (int): Number of available runs, capped at 25
            - cal_hash (str): Calibration parameter hash
            - sim_hash (str): Simulation parameter hash
            - time_range (str): Trading time range
            - total (int): Number of unique provider/exchange/symbol/date/
              scenario combinations

        Raises
        ------
        PulseAPIError
            If the key is invalid, revoked or expired — status 401.

        See Also
        --------
        get_sim_data : Download a cached run's files.
        get_sample_data : A small sample without spending download quota.

        Notes
        -----
        Available on every tier, and the way onto the platform without running
        anything: pick a group here and read it with :meth:`get_sim_data`.
        Only baseline simulations are cached — nothing with an execution algo.

        There is no ``provider`` or ``exchange`` filter, and groups are keyed
        by market as well as symbol, so a symbol cached under two providers
        appears twice; check ``provider`` and ``exchange`` on each group.

        Examples
        --------
        Every cached group:

        >>> cached = client.simulation.list_cached()
        >>> print(f"Found {cached['total']} cached simulation groups")
        >>> for sim in cached["simulations"]:
        ...     print(f"{sim['symbol']} {sim['date']} {sim['scenario']}: {sim['n_runs']} runs")
        ...     print(f"  Use sim_id: {sim['example_sim_id']}")

        Filtered by symbol:

        >>> cached = client.simulation.list_cached(symbol="700.HK")
        >>> for sim in cached["simulations"]:
        ...     print(f"{sim['date']} {sim['scenario']}: {sim['n_runs']} runs")

        Straight from a filtered group into a DataFrame:

        >>> cached = client.simulation.list_cached(
        ...     symbol="700.HK", scenario="flash_crash"
        ... )
        >>> if cached["simulations"]:
        ...     groups = cached["simulations"]
        ...     first = groups[0]
        ...     sim_id = first["example_sim_id"]
        ...     df = client.simulation.get_sim_data(sim_id)
        ...     print(df.head())
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        if date:
            params["date"] = date
        if scenario:
            params["scenario"] = scenario
        
        return self._client._request("GET", CACHED_PATH, params=params)

    def get_sample_data(self, path: str = "simulation_sample.zip"):
        """Download a sample dataset for 700.HK — 5 Monte Carlo runs, no configuration needed.

        The server picks the best available scenario (normal preferred) and returns
        sim_data.parquet and mid_price_by_min.parquet for each run as a ZIP.

        Parameters
        ----------
        path : str, default 'simulation_sample.zip'
            File path to save the ZIP to (default: "simulation_sample.zip").
            Pass None to return raw bytes instead.

        Returns
        -------
        bytes or None
            The ZIP content when ``path`` is None, otherwise None — the file
            is written to ``path`` instead.

        Raises
        ------
        PulseAPIError
            If no sample dataset has been published for this deployment — status
            404.

        See Also
        --------
        list_cached : The cached library the sample comes from.
        get_sim_data : The full files for one run.

        Notes
        -----
        Available on every tier and charged against nothing, so it is the
        cheapest way to see the shape of Pulse output before running anything.

        Examples
        --------
        Save to disk:

        >>> client.simulation.get_sample_data()  # writes simulation_sample.zip

        To a chosen path:

        >>> client.simulation.get_sample_data(path="data/sample.zip")

        Straight into DataFrames, without touching disk:

        >>> import io, zipfile
        >>> import polars as pl
        >>> data = client.simulation.get_sample_data(path=None)
        >>> with zipfile.ZipFile(io.BytesIO(data)) as zf:
        ...     for name in zf.namelist():
        ...         df = pl.read_parquet(io.BytesIO(zf.read(name)))
        ...         print(f"{name}: {df.shape}")
        """
        url = f"{self._client.base_url}{SAMPLE_PATH}"
        response = self._client._request_with_retries("GET", url)

        if path is None:
            return response.content

        with open(path, "wb") as f:
            f.write(response.content)

    def get_bulk_data(
        self,
        sim_ids: list,
        include_sim_data: bool = True,
        include_mid_price: bool = False,
        include_l2_by_second: bool = False,
    ):
        """Download data for multiple simulations as a ZIP file.

        Parameters
        ----------
        sim_ids : list
            List of simulation IDs to download
        include_sim_data : bool, default True
            Include sim_data.parquet files (default: True)
        include_mid_price : bool, default False
            Include mid_price_by_min.parquet files (default: False)
        include_l2_by_second : bool, default False
            Include l2_by_second.parquet files (default: False)

        Returns
        -------
        bytes
            ZIP content holding the requested parquet files, one directory per
            simulation.

        Raises
        ------
        PulseAPIError
            If ``sim_ids`` is empty, holds more than 100 ids, or every
            ``include_*`` flag is False (400); any ``sim_id`` is unknown or
            belongs to another account and is not in the cached library, or
            none of the requested files exist (404); or the free-tier
            download allowance would be exceeded (429, raised at once, as on
            :meth:`get_sim_data`).

        See Also
        --------
        get_sim_data : One file from one simulation, as a DataFrame.
        profile.downloads : Remaining free-tier allowance.

        Notes
        -----
        Free-tier quota: at most N **new** simulation groups per rolling
        24-hour window, 3 by default. One unit is consumed per distinct group
        — every Monte Carlo run of one scenario — not per call, run or file
        format, and membership is permanent: a group downloaded before is free
        to re-fetch forever. A request that would exceed the allowance returns
        HTTP 429 and charges nothing. Check with
        ``client.profile.downloads()``. Pro and demo tiers are unlimited.

        A requested file that does not exist for a simulation is left out,
        and so is one that fails to read while the ZIP is being streamed:
        both are skipped silently, with no error and no marker in the
        archive. Compare the ZIP's contents against what you asked for.

        Examples
        --------
        Bulk-download the default ``sim_data.parquet`` for several runs:

        >>> cached = client.simulation.list_cached(symbol="700.HK")
        >>> sim_ids = [s["example_sim_id"] for s in cached["simulations"]]
        >>> zip_bytes = client.simulation.get_bulk_data(sim_ids)
        >>> with open("simulation_data.zip", "wb") as f:
        ...     f.write(zip_bytes)

        Add the per-second L2 book:

        >>> zip_bytes = client.simulation.get_bulk_data(
        ...     sim_ids=sim_ids[:2],
        ...     include_sim_data=True,
        ...     include_l2_by_second=True,
        ... )

        Mid-price only, which keeps the ZIP small:

        >>> zip_bytes = client.simulation.get_bulk_data(
        ...     sim_ids,
        ...     include_sim_data=False,
        ...     include_mid_price=True,
        ... )

        Extract into DataFrames without writing the ZIP out:

        >>> import io, zipfile
        >>> import polars as pl
        >>> with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        ...     for name in zf.namelist():
        ...         if name.endswith(".parquet"):
        ...             df = pl.read_parquet(io.BytesIO(zf.read(name)))
        ...             print(f"{name}: {df.shape}")
        """
        payload = {
            "sim_ids": sim_ids,
            "include_sim_data": include_sim_data,
            "include_mid_price": include_mid_price,
            "include_l2_by_second": include_l2_by_second,
        }
        
        url = f"{self._client.base_url}{RESULTS_PATH}/bulk"
        # A read sent as POST for its body: safe to retry, and re-fetching
        # groups already downloaded is never charged again.
        response = self._client._request_with_retries(
            "POST", url, json=payload, idempotent=True
        )

        return response.content
