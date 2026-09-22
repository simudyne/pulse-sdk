# Simudyne Pulse Python SDK

Python client for the [Pulse](https://pulse.simudyne.com) synthetic market data API. Returns data as [Polars](https://pola.rs/) DataFrames.

## Installation

```bash
pip install simudyne-pulse
```

The distribution is named `simudyne-pulse`; the import name is `simudyne`:

```python
from simudyne import PulseABM
```

Requires Python 3.10+.

### Development builds

The `dev` branch is a prerelease channel. Pushes to it publish prerelease
versions (e.g. `0.6.0.dev1`) that are separate from the stable versions cut on
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

client = PulseABM(api_key="pk_live_...")

# List available exchanges, symbols, and dates
symbols = client.data.get_symbols(year=2024)
print(symbols)

# Fetch L2 order book data
df = client.data.get_L2("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T09:16:00")
print(df.head())
```

## API reference

### `PulseABM(api_key, base_url=None)`

| Parameter | Env variable | Default |
|-----------|-------------|---------|
| `api_key` | `SIMUDYNE_API_KEY` | required |
| `base_url` | `SIMUDYNE_BASE_URL` | Pulse API |

### `client.data`

All data methods return Polars DataFrames. Large result sets are automatically paginated.

```python
# Available exchanges, symbols, and dates
client.data.get_symbols(year=2024)

# L1: top of book (best bid/ask)
client.data.get_L1("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T10:00:00")

# L2: full order book (all levels)
client.data.get_L2("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T09:16:00")

# Orders: individual order events
client.data.get_orders("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T10:00:00")

# Trades: executed trades
client.data.get_trades("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T10:00:00")
```

**Parameters** (same for all data methods):

| Parameter | Type | Description |
|-----------|------|-------------|
| `exchange` | str | Exchange code (e.g. `HKEX`) |
| `sym` | str | Symbol name (e.g. `HSIJ4`) |
| `datetime_start` | str | Start time, ISO 8601 (e.g. `2024-04-02T09:15:00`) |
| `datetime_end` | str | End time, ISO 8601 |

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
