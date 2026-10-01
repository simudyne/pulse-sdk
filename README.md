# Simudyne Pulse Python SDK

Python client for the [Pulse](https://pulse.simudyne.com) synthetic market data API. Returns data as [Polars](https://pola.rs/) DataFrames.

## Installation

```bash
pip install "simudyne-pulse>=0.8.0"
```

0.7.x predates the current API: its validation and data calls are rejected by
pulse-api-pod 1.77 and later.

The distribution is named `simudyne-pulse`; the import name is `simudyne`:

```python
from simudyne import PulseABM
```

Requires Python 3.10+.

### Development builds

The `dev` branch is a prerelease channel. Pushes to it publish prerelease
versions (e.g. `0.8.0.dev1`) that are separate from the stable versions cut on
`prod`. `pip install simudyne-pulse` always resolves to the latest **stable**
release and ignores prereleases, so dev builds can never affect a normal
install.

To install the latest dev build, opt in with `--pre`:

```bash
pip install --pre simudyne-pulse
```

Only use dev builds for testing unreleased changes; they are not guaranteed
stable. Merge `dev` into `prod` to promote those changes to a stable release.

### Comparing named populations

Simulations are often not one population but several — a foundation model and
an ABM, or two versions of a model. Name them and the results compare them
instead of averaging them together:

```python
job = client.validation.run(
    symbol="TSCO", date="2026-06-23", provider="bmll", exchange="lse",
    sim_ids={"fm": fm_ids, "abm": abm_ids},
    plots=["statistical.radar", "stylised_facts.overall",
           "volume_correlation.overall"],
)
result = client.validation.get_job(job["job_id"], plot_dir="figs")
result["distances"]["fm"]["spread"]["l1"]
result["stylised_fact_verdicts"]["heavy_tails"]["simulated"]["abm"]
```

`distances`, `distributions`, the verdicts and the FID/MIND scores come back
keyed by name; the radar draws a polygon per population, the verdict table a
column each, and volume correlation puts historical first then a heatmap per
population. `sim_files` groups the same way.

A plain list is one unnamed population and keeps the flat shape exactly as
before. The historical day is measured once however many groups there are.

### Your own runs beside platform runs

`sim_ids` and `sim_files` can be given together — your own model against
platform simulations, on one set of figures, 25 runs in total across the two:

```python
job = client.validation.run(
    symbol="TSCO", date="2026-06-23", provider="bmll", exchange="lse",
    sim_files={"fm": ["my_run.parquet"]},
    sim_ids={"abm": abm_ids},
    plots=["statistical.radar", "stylised_facts.overall"],
)
```

With both present each source is a population of its own, so a bare list gets
a name rather than merging into whatever else is there:

| passed | populations |
| --- | --- |
| files mapping + ids list | its names, plus `platform` |
| files list + ids mapping | `uploaded`, plus its names |
| both lists | `uploaded` and `platform` |
| both mappings | their own names |
| either one alone | exactly as before |

The uploads are measured first and the platform runs follow.

`plots` is the only plot switch: unset draws nothing, `True` draws every
figure the enabled areas can draw, and a list draws just those ids. An area
switched off draws nothing either way.

| id | figure |
| --- | --- |
| `statistical.radar` | distance spider, one polygon per population |
| `statistical.distribution` | every metric's KDE |
| `statistical.distribution.{metric}` | one metric, e.g. `.spread` |
| `stylised_facts.overall` | the verdict table |
| `stylised_facts.fact` | every fact |
| `stylised_facts.fact.{name}` | one fact, e.g. `.heavy_tails` |
| `impact.response` | impact response by event type |
| `impact.event` | every event type |
| `impact.event.{type}` | one event type |
| `volume_correlation.levels` | level correlation heatmap |
| `volume_correlation.changes` | change correlation heatmap |
| `volume_correlation.overall` | both of the above |

Each returned figure carries the `id` it was asked for — match on that, not on
the filename.

### Working from a checkout

To run the SDK from source — editing it, or using unreleased changes — install
it editable **into the interpreter you will actually import from**. A notebook
kernel is frequently not the python on your `$PATH`:

```bash
# in a notebook, find the right interpreter first
import sys; print(sys.executable)

# then, with that path
<that python> -m pip install -e /path/to/pulse-sdk
```

Check which copy you loaded — this is worth doing whenever an attribute seems
to be missing:

```python
import simudyne
from importlib.metadata import version

print(simudyne.__file__)          # should be .../pulse-sdk/src/simudyne/...
print(version("simudyne-pulse"))
```

#### If an older install shadows it

The SDK was once published under the distribution name **`simudyne`**; it is
now **`simudyne-pulse`**. Both ship a module called `simudyne`, and the older
one installs a real directory while the editable install only adds a path
entry — so the old copy wins and you get errors like
`'PulseABM' object has no attribute 'validation'` from a version that predates
the feature. `pip list` shows both. Remove the obsolete one:

```bash
<that python> -m pip uninstall simudyne      # the old distribution
<that python> -m pip install -e /path/to/pulse-sdk
```

### Running the tests

```bash
uv run --with pytest --with requests --with pandas --with pyarrow \
    python -m pytest tests/ -q
```

No network: the client's `_request` is replaced with a recorder, so the tests
assert the exact payload the API would receive.

## Quick start

```python
from simudyne import PulseABM

client = PulseABM(api_key="pk_live_...")  # or set SIMUDYNE_API_KEY

# Days the agent-based model can simulate
cal = client.data.calibrated_data(symbol="700.HK")

# Run it, poll, read the generated book
job = client.simulation.run(
    symbol="700.HK", cal_date="2025-09-02",
    provider="omd", exchange="hkex_securities",
)
import time
while not client.simulation.get_job_status(job["job_id"])["is_complete"]:
    time.sleep(20)
book = client.simulation.get_sim_data(job["sim_ids"][0])
```

A foundation model runs through the same call with `engine="fm"` and a
`model_id`, which may be the model's production name (e.g.
`"flow-hkex-1-100M"`; see `client.fm.models()`). Fields that belong to the
other engine are sent and rejected by the API with a 422 rather than dropped.

Every method has a full numpy-style docstring (`help(client.simulation.run)`);
the user guide is at https://pulse.simudyne.com/docs.

## API reference

### `PulseABM(api_key, base_url=None)`

| Parameter | Env variable | Default |
|-----------|-------------|---------|
| `api_key` | `SIMUDYNE_API_KEY` | required |
| `base_url` | `SIMUDYNE_BASE_URL` | Pulse API |

| Resource | What it covers |
|----------|----------------|
| `client.data` | `available_data` (every symbol-day that exists), `calibrated_data` (what the ABM can run), `calibrate` |
| `client.simulation` | `run` (both engines), `run_lrm`, `get_jobs`, `get_job_status`, `get_job_results`, `get_job_logs`, sim files and downloads |
| `client.validation` | `run`, `get_job_status`, `get_job`, `list_jobs` — results carry `errors` per failed area |
| `client.fm` | `models`, `live`; admin: `registry`, `register`, `activate`, `deactivate` |
| `client.fix` | FIX session usage |
| `client.simulator_gym` | the interactive simulator websocket |

Failures raise `PulseAPIError` with `status_code`, `detail` (exactly as the
API sent it) and `errors`; `str(exc)` renders validation errors as
`field: message` lines.

### `client.profile`

```python
client.profile.get()      # Account info
client.profile.usage()    # API usage stats
```

### `client.api_keys`

```python
client.api_keys.list()                    # List active keys
client.api_keys.create(name="research")   # Create a new key
client.api_keys.revoke(key_id="key_...")  # Revoke a key
```

## Configuration

You can set your API key as an environment variable instead of passing it directly:

```bash
export SIMUDYNE_API_KEY=pk_live_...
```

```python
from simudyne import PulseABM
client = PulseABM()  # picks up SIMUDYNE_API_KEY automatically
```

## License

MIT
