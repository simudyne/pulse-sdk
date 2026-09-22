"""Tests for the FIX usage wrapper.

The venue is raw TCP and not reachable from this SDK; this is the one HTTP
endpoint a FIX client needs, so all there is to pin is the path and the
admin-only user_id passthrough.
"""

from simudyne.resources.fix import USAGE_PATH, FixResource


class FakeClient:
    def __init__(self):
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"total_runs": 3, "runs": []}

    @property
    def last(self):
        return self.calls[-1]


def test_own_usage_sends_no_params():
    client = FakeClient()
    out = FixResource(client).usage()
    assert client.last[:2] == ("GET", USAGE_PATH)
    assert client.last[2]["params"] is None
    assert out["total_runs"] == 3


def test_user_id_is_forwarded_for_admin_reads():
    client = FakeClient()
    FixResource(client).usage(user_id="user_abc")
    assert client.last[2]["params"] == {"user_id": "user_abc"}
