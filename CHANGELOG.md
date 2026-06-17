# CHANGELOG


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
