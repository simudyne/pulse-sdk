"""Retries resend only what is safe to send twice.

The client used to retry every method on 429/502/503/504 and on any timeout,
so a submit whose answer was lost — a 504 from the gateway after the API had
queued the job, or a read timeout — was sent again and queued a second job.
The API's only 429 is the free-tier download quota, which does not clear in
seconds, and it was retried for ~7 s before the same error was raised.
"""

import pytest
import requests
from urllib3.exceptions import NewConnectionError

from simudyne import PulseABM, PulseAPIError
from simudyne.client import _never_reached_server


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
        self._body = body if body is not None else {"detail": f"status {status}"}
        self.text = str(self._body)
        self.content = b""

    def json(self):
        return self._body


class FakeSession:
    """Plays back responses (or raises exceptions) in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.sent = []
        self.headers = {}
        self.verify = True

    def request(self, method, url, **kwargs):
        self.sent.append((method, url))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def client(monkeypatch):
    sleeps = []
    monkeypatch.setattr("simudyne.client.time.sleep", sleeps.append)
    c = PulseABM(api_key="pk_test", base_url="https://api.test", max_retries=3)
    c.sleeps = sleeps
    return c


def _with(client, outcomes):
    client.session = FakeSession(outcomes)
    return client.session


def _connect_refused():
    return requests.exceptions.ConnectionError(
        NewConnectionError(None, "Failed to establish a new connection: refused")
    )


OK = FakeResponse(200, {"ok": True})


class TestReadsAreRetried:
    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_a_get_is_retried_on_gateway_errors(self, client, status):
        session = _with(client, [FakeResponse(status), OK])
        assert client._request("GET", "/profile") == {"ok": True}
        assert len(session.sent) == 2

    @pytest.mark.parametrize(
        "error", [requests.exceptions.ReadTimeout(), requests.exceptions.ConnectionError()]
    )
    def test_a_get_is_retried_on_transport_errors(self, client, error):
        session = _with(client, [error, OK])
        assert client._request("GET", "/profile") == {"ok": True}
        assert len(session.sent) == 2

    def test_a_post_marked_idempotent_is_retried_like_a_read(self, client):
        session = _with(client, [FakeResponse(504), OK])
        resp = client._request_with_retries(
            "POST", "https://api.test/simulation/results/bulk", idempotent=True
        )
        assert resp is OK and len(session.sent) == 2

    def test_gives_up_after_max_retries(self, client):
        session = _with(client, [FakeResponse(502)] * 4)
        with pytest.raises(PulseAPIError) as exc:
            client._request("GET", "/profile")
        assert exc.value.status_code == 502
        assert len(session.sent) == 4
        assert client.sleeps == [1, 2, 4]


class TestSubmitsAreNotSentTwice:
    @pytest.mark.parametrize("status", [502, 504])
    def test_a_post_is_not_retried_on_502_or_504(self, client, status):
        session = _with(client, [FakeResponse(status), OK])
        with pytest.raises(PulseAPIError) as exc:
            client._request("POST", "/simulation/run", json={})
        assert exc.value.status_code == status
        assert len(session.sent) == 1

    def test_a_post_is_not_retried_on_a_read_timeout(self, client):
        session = _with(client, [requests.exceptions.ReadTimeout(), OK])
        with pytest.raises(requests.exceptions.ReadTimeout):
            client._request("POST", "/validation/run", json={})
        assert len(session.sent) == 1

    def test_a_delete_is_not_retried(self, client):
        """A revoke that worked but whose answer was lost would come back 404."""
        session = _with(client, [FakeResponse(504), OK])
        with pytest.raises(PulseAPIError):
            client._request("DELETE", "/api-keys/k1")
        assert len(session.sent) == 1

    def test_a_post_is_retried_on_503(self, client):
        """503 means the API did not act on it."""
        session = _with(client, [FakeResponse(503), OK])
        assert client._request("POST", "/simulation/run", json={}) == {"ok": True}
        assert len(session.sent) == 2

    @pytest.mark.parametrize(
        "error", [requests.exceptions.ConnectTimeout(), _connect_refused()]
    )
    def test_a_post_is_retried_when_it_never_reached_the_server(self, client, error):
        session = _with(client, [error, OK])
        assert client._request("POST", "/simulation/run", json={}) == {"ok": True}
        assert len(session.sent) == 2


class TestTooManyRequests:
    def test_the_download_quota_429_is_raised_at_once(self, client):
        session = _with(client, [FakeResponse(429), OK])
        with pytest.raises(PulseAPIError) as exc:
            client._request("GET", "/simulation/results/x/data/sim_data.parquet")
        assert exc.value.status_code == 429
        assert len(session.sent) == 1
        assert client.sleeps == []

    def test_a_rate_limit_429_with_retry_after_is_waited_out(self, client):
        session = _with(client, [FakeResponse(429, headers={"Retry-After": "3"}), OK])
        assert client._request("GET", "/profile") == {"ok": True}
        assert len(session.sent) == 2
        assert client.sleeps == [3.0]

    def test_retry_after_is_capped(self, client):
        _with(client, [FakeResponse(429, headers={"Retry-After": "3600"}), OK])
        client._request("GET", "/profile")
        assert client.sleeps == [60.0]


class TestNeverReachedServer:
    def test_connect_timeout(self):
        assert _never_reached_server(requests.exceptions.ConnectTimeout())

    def test_refused_connection(self):
        assert _never_reached_server(_connect_refused())

    def test_read_timeout_may_have_reached_it(self):
        assert not _never_reached_server(requests.exceptions.ReadTimeout())

    def test_a_dropped_connection_may_have_reached_it(self):
        assert not _never_reached_server(
            requests.exceptions.ConnectionError("Connection aborted.")
        )
