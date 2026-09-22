"""Foundation-model inference: generate a book from a trained model.

An FM run continues from real market data rather than simulating agents. You
name a market and a horizon; the platform slices the model's required context
out of that market's data, runs inference, and writes the output using the same
conventions as an agent-based run — so ``client.simulation`` reads FM results
with no special casing.

The only difference in a returned ``sim_id`` is the ``gen_method`` field, which
reads ``FM-{model_id}_v{version}`` where an ABM run reads ``ABM_v{version}``.

Workflow:
    1. ``models()`` — what can run here, and what each model accepts
    2. ``available_data(model_id=...)`` — what it can be prompted with
    3. ``run(...)`` — submit; returns a job_id and its sim_ids up front
    4. ``job_status(job_id)`` until ``complete`` or ``failed``
    5. ``client.simulation.get_sim_data(sim_id)`` — read the generated book
"""

MODELS_PATH = "/fm/models"
AVAILABLE_DATA_PATH = "/fm/available-data"
RUN_PATH = "/fm/run"
LIVE_PATH = "/fm/live"
JOBS_PATH = "/fm/jobs"

#: Statuses that mean the run has stopped. Everything else — including any
#: state added later — means still in flight, so a poller needs no changes.
TERMINAL_STATUSES = ("complete", "failed")


class FmResource:
    """Generate order books from a trained foundation model.

    Reached as ``client.fm``. An FM run continues from real market data rather
    than simulating agents, but writes its output with the same conventions as
    an agent-based run, so results are read back through ``client.simulation``.

    Every call on this resource requires a pro-tier key.

    Examples
    --------
    The full workflow, from picking a model to reading the generated book:

    >>> import time
    >>> from simudyne.resources.fm import TERMINAL_STATUSES
    >>> models = client.fm.models()["models"]
    >>> model = models[0]
    >>> job = client.fm.run(
    ...     model_id=model["model_id"],
    ...     symbol="700",
    ...     cal_date="2025-09-02",
    ...     provider="bmll",
    ...     exchange="hkex_securities",
    ...     duration_minutes=30,
    ... )
    >>> while client.fm.job_status(job["job_id"])["status"] not in TERMINAL_STATUSES:
    ...     time.sleep(30)
    >>> sim_ids = job["sim_ids"]
    >>> book = client.simulation.get_sim_data(sim_ids[0])
    """

    def __init__(self, client):
        self._client = client

    def models(self):
        """Foundation models active in this environment.

        Requires a pro-tier key.

        Returns
        -------
        dict
            Contains ``models``, a list of model dicts, each with:

            - model_id (str): the id to pass to :meth:`run`
            - version (str): the model build version
            - production_name (str): branding name, empty for dev builds
            - supported_data (list of dict): ``{provider, exchange}`` markets
              the model accepts a prompt from; empty means any
            - min_prompt_rows (int or None): context rows it needs to start
            - model_args (dict): the knobs it accepts, each
              ``{type, default, min, max, description}``
            - resources (dict): ``{cpu, memory, gpu}`` it is scheduled with

        Raises
        ------
        PulseAPIError
            If the key is not pro tier — status 403.

        Examples
        --------
        >>> for m in client.fm.models()["models"]:
        ...     print(m["model_id"], m["version"], sorted(m["model_args"]))

        Inspect one model's knobs before overriding them:

        >>> models = client.fm.models()["models"]
        >>> first = models[0]
        >>> knobs = first["model_args"]
        >>> knobs["temperature"]
        {'type': 'float', 'default': 1.0, 'min': 0.1, 'max': 2.0, ...}
        """
        return self._client._request("GET", MODELS_PATH)

    def available_data(
        self,
        model_id: str = None,
        symbol: str = None,
        q: str = None,
        provider: str = None,
        exchange: str = None,
        date: str = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """What a foundation model can be prompted with.

        An FM prompt is the opening rows of a REAL trading day, so this reads
        the raw-data registry rather than the calibrated catalog behind
        ``client.data.get_available_symbols()`` — it reports every symbol-day
        that exists, including days the ABM pipeline never ran. No calibration
        state is reported, because none applies.

        Every filter is applied server-side: the registry holds the whole
        vendor universe (tens of thousands of symbol-days) and is never
        returned whole. Requires a pro-tier key.

        Parameters
        ----------
        model_id : str, optional
            Restrict to the markets this model's ``supported_data``
            declares, so the result is exactly what it will accept at
            run(). An unknown id is a 404.
        symbol : str, optional
            Exact symbol, e.g. "700".
        q : str, optional
            Case-insensitive substring match over the symbol.
        provider : str, optional
            Data provider, e.g. "bmll".
        exchange : str, optional
            Exchange protocol, e.g. "lse" or "hkex_securities".
        date : str, optional
            Trading date "YYYY-MM-DD"; keeps only symbols with data on
            it, and narrows each entry's dates to it.
        limit : int, default 50
            Max symbols to return (1-200, default 50).
        offset : int, default 0
            Symbols to skip, for paging alongside limit.

        Returns
        -------
        dict
            Paged registry slice containing:

            - total (int): match count before paging
            - limit (int): the page size that was applied
            - offset (int): the offset that was applied
            - symbols (list of dict): one
              ``{symbol, provider, exchange, dates}`` per matching symbol

        Raises
        ------
        PulseAPIError
            If ``model_id`` is unknown (404), ``limit`` is outside 1-200
            (400), or the key is not pro tier (403).

        Examples
        --------
        >>> data = client.fm.available_data(model_id="tradefm-hkex", limit=5)
        >>> print(data["total"])
        >>> for s in data["symbols"]:
        ...     print(s["symbol"], s["provider"], s["exchange"], len(s["dates"]))

        Page through everything a model accepts:

        >>> offset = 0
        >>> while True:
        ...     page = client.fm.available_data(
        ...         model_id="tradefm-hkex", limit=200, offset=offset
        ...     )
        ...     if not page["symbols"]:
        ...         break
        ...     offset += len(page["symbols"])
        """
        params = {
            k: v for k, v in {
                "model_id": model_id,
                "symbol": symbol,
                "q": q,
                "provider": provider,
                "exchange": exchange,
                "date": date,
                "limit": limit,
                "offset": offset,
            }.items() if v is not None
        }
        return self._client._request("GET", AVAILABLE_DATA_PATH, params=params)

    def run(
        self,
        model_id: str,
        symbol: str = None,
        cal_date: str = None,
        provider: str = None,
        exchange: str = None,
        duration_minutes: float = None,
        horizon: int = None,
        n_runs: int = 1,
        seed: int = 42,
        device: str = None,
        model_args: dict = None,
        exec_algos: list = None,
        prompt: dict = None,
    ):
        """Submit a foundation-model inference job.

        Returns as soon as the job is queued, with the sim_ids it will produce
        — they are queryable from that moment. Poll ``job_status(job_id)``
        until the status is terminal, then read each sim with
        ``client.simulation.get_sim_data(sim_id)``.

        Requires a pro-tier key.

        Parameters
        ----------
        model_id : str
            A model from models(). Required.
        symbol : str, optional
            Instrument to prompt from, e.g. "700".
        cal_date : str, optional
            Trading day "YYYY-MM-DD" whose opening rows become the
            prompt.
        provider : str, optional
            Data provider the day is sourced from, e.g. "bmll". Must
            be a market the model's ``supported_data`` allows.
        exchange : str, optional
            Exchange protocol, e.g. "hkex_securities".
        duration_minutes : float, optional
            How much wall-clock market time to generate,
            measured from the first row of the warm-start context. Prefer
            this over ``horizon``: an illiquid symbol simply produces
            fewer frames for the same duration.
        horizon : int, optional
            Raw frame count to generate. The older form — it applies
            only when ``duration_minutes`` is unset.
        n_runs : int, default 1
            Monte Carlo runs (1-8). Per-run seeds are derived from
            ``seed`` exactly as the ABM derives them, and the run index is
            the ``mc_number`` in the returned sim_ids.
        seed : int, default 42
            Master random seed.
        device : str, optional
            "cpu", "gpu", or None for the model's own default.
        model_args : dict, optional
            Overrides for the model's declared knobs — see the
            ``model_args`` of models(). Unknown or out-of-range keys are
            rejected with a 400.
        exec_algos : list, optional
            Execution algorithms, same config shape as
            ``client.simulation.run()``. At most one per job, and it needs
            a real market day rather than test data.
        prompt : dict, optional
            Prompt source override. Defaults server-side to
            ``{"source": "testdata"}`` when no market is named.

        Returns
        -------
        dict
            Submission result containing:

            - job_id (str): handle for :meth:`job_status` and :meth:`job_logs`
            - model_id (str): the model that was scheduled
            - version (str): the model build version
            - sim_ids (list of str): one per Monte Carlo run, queryable
              immediately and readable once the job completes

        Raises
        ------
        PulseAPIError
            If ``model_id`` is unknown (404); if ``model_args`` holds an
            unknown or out-of-range key, ``n_runs`` is outside 1-8, or the
            named market is not in the model's ``supported_data`` (400); or if
            the key is not pro tier (403).

        Examples
        --------
        >>> job = client.fm.run(
        ...     model_id="tradefm-hkex",
        ...     symbol="700",
        ...     cal_date="2025-09-02",
        ...     provider="bmll",
        ...     exchange="hkex_securities",
        ...     duration_minutes=30,
        ...     model_args={"temperature": 0.8},
        ... )
        >>> print(job["job_id"], job["sim_ids"])

        Several Monte Carlo runs off one prompt:

        >>> job = client.fm.run(
        ...     model_id="tradefm-hkex",
        ...     symbol="700",
        ...     cal_date="2025-09-02",
        ...     provider="bmll",
        ...     exchange="hkex_securities",
        ...     duration_minutes=30,
        ...     n_runs=4,
        ...     seed=7,
        ... )
        >>> len(job["sim_ids"])
        4

        Against the built-in test data, with no market named:

        >>> job = client.fm.run(model_id="tradefm-hkex", horizon=5000)
        """
        from simudyne.resources.simulation import SimulationResource

        payload = {"model_id": model_id, "n_runs": n_runs, "seed": seed}
        optional = {
            "symbol": symbol,
            "cal_date": cal_date,
            "provider": provider,
            "exchange": exchange,
            "duration_minutes": duration_minutes,
            "horizon": horizon,
            "device": device,
            "prompt": prompt,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        if model_args:
            payload["model_args"] = model_args
        if exec_algos:
            payload["exec_algos"] = SimulationResource._serialize_exec_algos(exec_algos)

        return self._client._request("POST", RUN_PATH, json=payload)

    def job_status(self, job_id: str):
        """Status of a foundation-model job.

        Parameters
        ----------
        job_id : str
            The job ID returned by run().

        Returns
        -------
        dict
            Job state containing ``job_id``, ``status``, ``message``,
            ``detail``, ``started_at`` and ``completed_at``. ``status`` is one
            of:

            - "queued": accepted, no compute assigned yet
            - "provisioning": waiting on capacity — a GPU model may need a
              machine started for it. ``detail`` carries the scheduler's
              reason, so a GPU stockout is distinguishable from a stuck run
            - "starting": compute assigned, image and weights loading
            - "running": generating
            - "complete" / "failed": the only terminal values

            ``message`` is a ready-to-display label for the current state;
            ``detail`` is empty unless something is holding the run up.

        Raises
        ------
        PulseAPIError
            If ``job_id`` is unknown or belongs to another account — status
            404.

        See Also
        --------
        TERMINAL_STATUSES : The statuses that mean the run has stopped.

        Examples
        --------
        >>> import time
        >>> from simudyne.resources.fm import TERMINAL_STATUSES
        >>> while True:
        ...     s = client.fm.job_status(job_id)
        ...     print(s["status"], s.get("message", ""))
        ...     if s["status"] in TERMINAL_STATUSES:
        ...         break
        ...     time.sleep(30)
        """
        return self._client._request("GET", f"{JOBS_PATH}/{job_id}/status")

    def job_logs(self, job_id: str):
        """Pod logs for a foundation-model job.

        Parameters
        ----------
        job_id : str
            The job ID returned by run().

        Returns
        -------
        dict
            Contains ``job_id`` and ``logs`` — the raw pod log text, newline
            separated.

        Raises
        ------
        PulseAPIError
            If ``job_id`` is unknown or belongs to another account (404), or
            the pod has been reaped and its logs are gone (410).

        Examples
        --------
        >>> print(client.fm.job_logs(job_id)["logs"])

        The usual reason to reach for logs is a failed job:

        >>> status = client.fm.job_status(job_id)
        >>> if status["status"] == "failed":
        ...     print(status["detail"])
        ...     logs = client.fm.job_logs(job_id)["logs"]
        ...     print(logs[-2000:])
        """
        return self._client._request("GET", f"{JOBS_PATH}/{job_id}/logs")

    def live(
        self,
        model_id: str,
        horizon: int = None,
        seed: int = 42,
        model_args: dict = None,
        prompt: dict = None,
    ):
        """Start a live streaming session instead of a batch job.

        Returns the token a live chart client uses to connect. Requires a
        pro-tier key.

        Parameters
        ----------
        model_id : str
            A model from models().
        horizon : int, optional
            Frames to generate.
        seed : int, default 42
            Master random seed.
        model_args : dict, optional
            Overrides for the model's declared knobs.
        prompt : dict, optional
            Prompt source override.

        Returns
        -------
        dict
            Contains ``token`` — the connection token a live chart client
            presents — plus ``job_id`` and ``model_id``.

        Raises
        ------
        PulseAPIError
            If ``model_id`` is unknown (404), ``model_args`` holds an unknown
            or out-of-range key (400), or the key is not pro tier (403).

        Examples
        --------
        >>> session = client.fm.live(model_id="tradefm-hkex", horizon=5000)
        >>> print(session["token"])

        The session is still a job, so its status and logs read back the same
        way as a batch run:

        >>> client.fm.job_status(session["job_id"])["status"]
        'running'
        """
        payload = {"model_id": model_id, "seed": seed}
        if horizon is not None:
            payload["horizon"] = horizon
        if model_args:
            payload["model_args"] = model_args
        if prompt is not None:
            payload["prompt"] = prompt
        return self._client._request("POST", LIVE_PATH, json=payload)
