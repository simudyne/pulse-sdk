# CHANGELOG


## v0.7.3 (2026-09-22)

### Bug Fixes

- **sdk**: Numpy-style docstrings for the released endpoints
  ([`11601e9`](https://github.com/simudyne/pulse-sdk/commit/11601e901867995d6d38144feca95cf2fc2d0567))

Docs only — every file is byte-identical to 0.7.2 once docstrings are stripped, so no behaviour
  changes.

- Class docstrings for the 5 resources that had none, Examples sections for the methods missing one,
  and Raises throughout - Lift examples out of Returns blocks into real Examples sections - Every
  Raises block checked against pulse-api-pod rather than inferred: documents the 503/500 paths the
  SDK proxies, the 400s on bulk download, and drops a claimed API-key limit that does not exist -
  Rewrite example subscripts that mkdocs-autorefs misread as reference links, taking the pulse-sdk
  docs build to zero warnings

validation.py is left alone: its API on prod differs from dev's, so its docstrings need writing
  against this signature rather than porting.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>


## v0.7.2 (2026-09-21)

### Bug Fixes

- **docs**: Convert the SDK docstrings to numpy style
  ([`653b1e4`](https://github.com/simudyne/pulse-sdk/commit/653b1e4b330dbf8adf44d627b29ab020da673f3c))

pulse-docs sets docstring_style: numpy in mkdocs.yml and renders the SDK from this branch, but the
  docstrings here were Google style. griffe's numpy parser does not recognise Args:/Returns:, so
  each one collapsed into a single undifferentiated text section and the SDK reference rendered as
  flat prose with no parameter or returns tables.

- Convert the 23 Google-style docstrings across simulation, validation, simulator_gym and data -
  Give api_keys.create/list/revoke and profile.get/usage docstrings at all; five endpoints had none,
  so they rendered as a bare signature - Rewrite profile.downloads in numpy sections

All 34 public methods now parse with griffe's numpy parser, 72 parameters among them, with no
  undocumented arguments and no Google-style left.

Docstrings only: the executable code of every touched file is identical to origin/prod once
  docstrings are stripped. Nothing from dev is included.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.7.1 (2026-08-18)

### Bug Fixes

- **validation**: Restore the pre-0.7.0 run flag defaults
  ([`7eb73fe`](https://github.com/simudyne/pulse-sdk/commit/7eb73fec5a90868e0facd977d7cfa02e916f0303))

0.7.0 made run_metrics/run_impact/run_fid tri-state and omitted them when unset, which changed
  behaviour for existing callers: the API's non-demo default for run_impact is True, so a pro user
  passing no flags started paying for the impact pass that this SDK had always defaulted off. It
  also inserted a parameter mid-signature, shifting positional arguments.

- Send run_metrics/run_impact/run_fid explicitly again, with their original defaults, so any 0.6.x
  caller behaves identically - Keep run_stylised_facts as the one addition, appended last in both
  run() and run_pipeline() so no positional argument moves; omitted when unset so demo accounts
  still get stylised facts from the tier default

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>


## v0.7.0 (2026-08-18)

### Features

- **validation**: Let the tier pick which validation passes run
  ([`a710031`](https://github.com/simudyne/pulse-sdk/commit/a7100314be2e03dc3a0105ac9c217dc89e3dd50a))

- Default run_metrics/run_impact/run_fid to None and omit them from the payload when unset, so the
  API applies the caller's tier default instead of an SDK-side False that opts demo accounts out of
  their extra results - Add run_stylised_facts, which the API accepted but the SDK never exposed -
  Document the demo-only result fields on get_job()

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>


## v0.6.1 (2026-08-05)

### Bug Fixes

- **simulation**: Correct stale flash_crash/buy_panic scenario defaults
  ([`af10951`](https://github.com/simudyne/pulse-sdk/commit/af1095184277f593aeadded35fac34ac8d598823))

- both advertised 22.0/0.19/500ms while the engine has used 150.0/0.02/100ms since pulse 2.4.7
  (07c176e1), so anyone sizing a scenario from get_scenario_defaults got ~7x the impact shown - note
  the mirroring requirement against EIB/calcs/scenarios.py, whose builder signatures SimulationRun
  backfills from

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>


## v0.6.0 (2026-08-05)


## v0.6.0-dev.2 (2026-08-04)

### Documentation

- **sdk**: Permanent group membership semantics for the download quota
  ([`b7c6584`](https://github.com/simudyne/pulse-sdk/commit/b7c6584854afa55e2b4d518ed47aa6b9cf0becf7))

- downloads() documents downloaded_groups and new-groups-per-window counting -
  get_sim_data/get_bulk_data note the per-file quota and free re-fetches

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- **data**: Forward catalog filters from get_available_symbols
  ([`675d98d`](https://github.com/simudyne/pulse-sdk/commit/675d98d26e88a52a313ea1043321019946e8e5ec))

- Accept optional symbol/exchange/provider/date/limit/offset and pass them as query params to GET
  /data/available-symbols - No-argument calls behave exactly as before

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.6.0-dev.1 (2026-07-16)

### Chores

- **ci**: Add manual test workflow and sync dev with prod rename
  ([`7233349`](https://github.com/simudyne/pulse-sdk/commit/7233349592a65932a508827979d26c703b9b872f))

- Add .github/workflows/test.yml with workflow_dispatch trigger running pytest - Add optional "test"
  dependency group (pytest) to pyproject.toml - Bring dev up to date with the main->prod rename and
  PyPI publish step

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

- **release**: Add dev prerelease channel alongside stable main
  ([`d5b0943`](https://github.com/simudyne/pulse-sdk/commit/d5b094353afa50cc40f6df0ff1ac9bff2e13d724))

- Configure semantic-release branches: main (stable) + dev (-dev.N prereleases) - Trigger release
  workflow on pushes to dev as well as main - Document `pip install git+...@dev` dev builds in
  README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **release**: Rename stable branch main -> prod
  ([`1e3ad4b`](https://github.com/simudyne/pulse-sdk/commit/1e3ad4bfa2744508885cc97a61b3cbd90de5b7d8))

- Point semantic-release stable channel at prod (was main) - Trigger release workflow on prod
  instead of main - Update README promote-to-stable note

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### Features

- **profile**: Add downloads() for the bulk-download quota endpoint
  ([`873893c`](https://github.com/simudyne/pulse-sdk/commit/873893c6e1d724fc334ec85b4f7ac750b23b759a))

- client.profile.downloads() wraps GET /profile/downloads (limit/used/remaining) - document
  free-tier quota semantics and 429 behaviour on get_bulk_data

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.5.2 (2026-06-17)

### Bug Fixes

- Update client to catch connection errors
  ([`e26d3bf`](https://github.com/simudyne/pulse-sdk/commit/e26d3bf4b54e8849b2cdb1f2e07a52f4e28daedc))

### Documentation

- **sdk**: Use provider="omd" in examples (was "hkex")
  ([`687061b`](https://github.com/simudyne/pulse-sdk/commit/687061bc6dc2e4c74654208448c87f51341f4336))

The HKEX provider was renamed to 'omd'; run()/calibrate() docstring examples now match the API's
  valid providers.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>


## v0.5.1 (2026-06-05)


## v0.5.0 (2026-06-03)

### Features

- Add PlotDisplay with distributions/distances/impact_response methods
  ([`dc69de4`](https://github.com/simudyne/pulse-sdk/commit/dc69de435f56f5c0deabcfb68e2c526d74826032))


## v0.4.1 (2026-06-03)

### Bug Fixes

- Add rescale_volumes and lot_size to run_pipeline
  ([`890c47f`](https://github.com/simudyne/pulse-sdk/commit/890c47ff87382aa06de5feafe3c52772927fa573))


## v0.4.0 (2026-06-03)

### Features

- Change naming of val function
  ([`1302a4c`](https://github.com/simudyne/pulse-sdk/commit/1302a4caf945aacff02c94c95c7ddf7f061004a6))


## v0.3.0 (2026-06-02)

### Documentation

- Fix exec_algos documentation to match actual API
  ([`fe22ee8`](https://github.com/simudyne/pulse-sdk/commit/fe22ee8e1db47e6acc312c5fbd8e59d12752d744))

- Changed `horizon (timedelta)` to `horizon: SECONDS` (int) - Documented order_size sign convention:
  negative=buy, positive=sell - Fixed example: `horizon_mins: 60` → `horizon: 3600` - Added buy
  order example

Addresses UAT issues #2 (kwarg mismatch) and #5 (sign convention).

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>

### Features

- Adding validation endpoints to the SDK
  ([`d5e6708`](https://github.com/simudyne/pulse-sdk/commit/d5e6708c2ef2947ce959089a5cb44a82899cf9e4))


## v0.2.0 (2026-05-14)

### Bug Fixes

- Align sample data with pulse-api-pod
  ([`c79b372`](https://github.com/simudyne/pulse-sdk/commit/c79b372a114102a423bf78c93bffe81545d7ffad))


## v0.1.3 (2026-05-05)

### Bug Fixes

- Error logging
  ([`7b488b0`](https://github.com/simudyne/pulse-sdk/commit/7b488b0cff6b53194cd93992c62e78e83e678b9b))

### Features

- Add l2_by_second parquets
  ([`51d6d2a`](https://github.com/simudyne/pulse-sdk/commit/51d6d2ac81327037e520bdd621797e9231755850))


## v0.1.2 (2026-05-05)


## v0.1.1 (2026-05-05)

### Bug Fixes

- @main for release
  ([`247a6da`](https://github.com/simudyne/pulse-sdk/commit/247a6daa064fd3664dc2cef78f35219d8639074a))

- Added exponetial backoff and timeout.
  ([`f6810f0`](https://github.com/simudyne/pulse-sdk/commit/f6810f061ddd540379eee668210eea81d3ce74cd))

- Error logging
  ([`806720d`](https://github.com/simudyne/pulse-sdk/commit/806720d09058050749e5b0b98d3f899d9db25b11))

- Resolve build failure and clean up release workflow
  ([`40f5fb4`](https://github.com/simudyne/pulse-sdk/commit/40f5fb47d6c81d27eba27d352d935d0fdb4d9c85))

- Serialise the exec_algo params
  ([`05cf196`](https://github.com/simudyne/pulse-sdk/commit/05cf196c43e2d477f73f71623e501fa469385c15))

- Updated to improve the security pratices
  ([`824fc2b`](https://github.com/simudyne/pulse-sdk/commit/824fc2bef1295d3d88e6c6c42d99dcffa7e08d21))

- Updating api to include rl gym and point at the new cluster
  ([`01e9f08`](https://github.com/simudyne/pulse-sdk/commit/01e9f082f178b5cb8f1d6940e0d91502fa06aa24))

- Updating the new base url
  ([`df9b3f8`](https://github.com/simudyne/pulse-sdk/commit/df9b3f80e0edd186e5602ec7655d00ed9de4fdb5))


## v0.1.0 (2026-02-19)
