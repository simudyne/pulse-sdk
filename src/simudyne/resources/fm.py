"""The foundation-model registry: what can run here, and what each accepts.

RUNNING a foundation model is not here. ``client.simulation.run(engine="fm")``
submits every simulation, agent-based or foundation-model, and
``client.simulation`` polls and reads them both — an FM sim carries the same
canonical ``sim_id``, differing only in its ``gen_method`` field
(``FM-{model_id}_v{version}`` rather than ``ABM_v{version}``).

What remains here is the registry, which is a catalogue of engines rather than
a simulation, and the live streaming session, which has no job and no sim_id
and so shares no lifecycle with the rest.

Workflow:
    1. ``models()`` — what can run here, and what each model accepts
    2. ``client.data.available_data(model_id=...)`` — what it can be prompted
       with
    3. ``client.simulation.run(engine="fm", model_id=...)`` — submit; returns a
       job_id and its sim_ids up front
    4. ``client.simulation.get_job_status(job_id)`` until it is complete
    5. ``client.simulation.get_sim_data(sim_id)`` — read the generated book
"""

MODELS_PATH = "/fm/models"
LIVE_PATH = "/fm/live"


class FmResource:
    """The foundation models registered in this environment.

    Reached as ``client.fm``. Use it to discover what can run and what each
    model accepts, then submit through ``client.simulation.run(engine="fm")``
    like any other simulation.

    Every call on this resource requires a pro-tier key.

    Examples
    --------
    The full workflow, from picking a model to reading the generated book —
    note that only the first step is on this resource:

    >>> import time
    >>> model = client.fm.models()["models"][0]
    >>> job = client.simulation.run(
    ...     engine="fm",
    ...     model_id=model["model_id"],
    ...     symbol="700",
    ...     cal_date="2025-09-02",
    ...     provider="bmll",
    ...     exchange="hkex_securities",
    ...     duration_minutes=30,
    ... )
    >>> while not client.simulation.get_job_status(job["job_id"])["is_complete"]:
    ...     time.sleep(30)
    >>> book = client.simulation.get_sim_data(job["sim_ids"][0])
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

    def live(
        self,
        model_id: str,
        horizon: int = None,
        seed: int = 42,
        model_args: dict = None,
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

        A live session is not a batch job: nothing is queued, no ``sim_id`` is
        minted, and there is no status to poll. The token is the whole
        interface.
        """
        payload = {"model_id": model_id, "seed": seed}
        if horizon is not None:
            payload["horizon"] = horizon
        if model_args:
            payload["model_args"] = model_args
        return self._client._request("POST", LIVE_PATH, json=payload)
