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
REGISTRY_PATH = "/fm/models/registry"
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

            - model_id (str): the id to pass as ``model_id`` to
              :meth:`~simudyne.resources.simulation.SimulationResource.run`
            - version (str): the model build version
            - production_name (str): the name it is promoted under,
              ``{model}-{market}-{version}-{size}`` e.g. "flow-hkex-1-100M";
              empty for dev builds. Accepted anywhere ``model_id`` is.
            - supported_data (list of dict): ``{provider, exchange}`` markets
              the model accepts a prompt from; empty means any
            - min_prompt_rows (int or None): context rows it needs to start
            - model_args (dict): the knobs it accepts, each
              ``{type, default, min, max, choices, description}``
            - resources (dict): ``{cpu, memory, gpu}`` it is scheduled with

        Raises
        ------
        PulseAPIError
            If the key is not pro tier — status 403.

        See Also
        --------
        simudyne.resources.data.DataResource.available_data : Days a model will accept, via model_id.
        simudyne.resources.simulation.SimulationResource.run : Run a model with engine="fm".
        live : Stream a model live instead of in batch.

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

    def registry(self):
        """Admin: the latest registry row for every model, active or not.

        :meth:`models` lists only what can run; this includes deactivated
        models, which is what to read before :meth:`activate` or
        :meth:`deactivate`.

        Returns
        -------
        dict
            ``{env, models}``: the environment, and the latest row per model
            with the fields :meth:`models` returns plus ``active`` and
            ``updated_by``. The container image is not returned.

        Raises
        ------
        PulseAPIError
            If the key is not an admin key — status 403.

        See Also
        --------
        models : The active models only, for any pro key.
        register : Add a model or a new version of one.

        Examples
        --------
        >>> state = client.fm.registry()
        """
        return self._client._request("GET", REGISTRY_PATH)

    def register(
        self,
        model_id: str,
        version: str,
        image: str,
        *,
        resources: dict | None = None,
        model_args: dict | None = None,
        supported_data: list | None = None,
        min_prompt_rows: int | None = None,
        production_name: str = "",
        active: bool = True,
    ):
        """Admin: register a model image, or a new version of one.

        The registry is append-only and the latest row per model wins, so
        registering an existing ``model_id`` replaces what :meth:`models`
        reports for it. Promotion to staging and prod normally goes through
        pulse-fm-inference's ``promote-model`` workflow, which calls this.

        Parameters
        ----------
        model_id : str
            The model's id, e.g. "flob-adaln-rf-1s".
        version : str
            The build version, e.g. "1.0.14".
        image : str
            The container image to run.
        resources : dict, optional
            ``{"cpu": "2", "memory": "4Gi", "gpu": 0}``.
        model_args : dict, optional
            The knobs the model accepts: ``{"name": default}`` or
            ``{"name": {"type", "default", "min", "max", "choices",
            "description"}}``. ``"choices": [true]`` pins a bool.
        supported_data : list of dict, optional
            ``[{"provider", "exchange"}, ...]`` markets it accepts a prompt
            from; empty means any.
        min_prompt_rows : int, optional
            Context rows it needs to start inference.
        production_name : str, default ""
            The name to promote it under, ``{model}-{market}-{version}-{size}``.
        active : bool, default True
            Whether :meth:`models` lists it.

        Returns
        -------
        dict
            ``{registered, image_verified}``: the row written, and whether the
            image was found in its registry.

        Raises
        ------
        PulseAPIError
            If the key is not an admin key (403), or a field is rejected (400
            or 422).

        See Also
        --------
        registry : What is registered now.
        deactivate : Withdraw a model.

        Examples
        --------
        >>> client.fm.register(
        ...     "flob-adaln-rf-1s", "1.0.14",
        ...     "docker.io/simudyneltd/flob-adaln-rf-1s:1.0.14",
        ...     supported_data=[{"provider": "bmll", "exchange": "hkex_securities"}],
        ...     production_name="flow-hkex-1-100M",
        ... )
        """
        payload = {
            "model_id": model_id,
            "version": version,
            "image": image,
            "production_name": production_name,
            "active": active,
        }
        for name, value in (
            ("resources", resources), ("model_args", model_args),
            ("supported_data", supported_data), ("min_prompt_rows", min_prompt_rows),
        ):
            if value is not None:
                payload[name] = value
        return self._client._request("POST", MODELS_PATH, json=payload)

    def activate(self, model_id: str):
        """Admin: list a deactivated model again.

        Parameters
        ----------
        model_id : str
            The registry ``model_id`` (not the production name).

        Returns
        -------
        dict
            ``{registered}``: the registry row written, with ``active``
            flipped.

        Raises
        ------
        PulseAPIError
            If the key is not an admin key (403) or the model is unknown (404).

        See Also
        --------
        deactivate : The reverse.

        Examples
        --------
        >>> client.fm.activate("flob-adaln-rf")
        """
        return self._client._request("POST", f"{MODELS_PATH}/{model_id}/activate")

    def deactivate(self, model_id: str):
        """Admin: withdraw a model from :meth:`models`.

        Its history stays in the registry and :meth:`activate` restores it.

        Parameters
        ----------
        model_id : str
            The registry ``model_id`` (not the production name).

        Returns
        -------
        dict
            ``{registered}``: the registry row written, with ``active``
            flipped.

        Raises
        ------
        PulseAPIError
            If the key is not an admin key (403) or the model is unknown (404).

        See Also
        --------
        activate : The reverse.
        registry : Which models are active.

        Examples
        --------
        >>> client.fm.deactivate("flob-adaln-rf")
        """
        return self._client._request("POST", f"{MODELS_PATH}/{model_id}/deactivate")

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
            A ``model_id`` from :meth:`models`.
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

        See Also
        --------
        models : Models and what each accepts.
        simudyne.resources.fix.FixResource.usage : What a FIX session has run.

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
