"""ApiClient against the recording transport (design §4.1)."""

from __future__ import annotations

import email.utils
import logging
import time
import xml.etree.ElementTree as ET

import httpx
import pytest
from azure.core.credentials import AccessToken
from recording_transport import RecordingTransport, json_response
from rich.logging import RichHandler

import dazure._api_client
from dazure import ApiClient, ApiError, DazureError
from dazure._api_client import BearerAuth, backoff_default

INFO = "\N{INFORMATION SOURCE}"
HOST = "https://api.example.com"


@pytest.fixture
def transport(monkeypatch) -> RecordingTransport:
    """Every ApiClient built in the test sends through this transport."""
    t = RecordingTransport()
    monkeypatch.setattr(dazure._api_client, "_transport", lambda: t)
    return t


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Retries record their waits here instead of sleeping."""
    waits: list[float] = []
    monkeypatch.setattr(dazure._api_client, "_sleep", waits.append)
    return waits


@pytest.fixture(autouse=True)
def _restore_http_logger():
    log = logging.getLogger("dazure.http")
    handlers, level = list(log.handlers), log.level
    yield
    log.handlers[:] = handlers
    log.setLevel(level)


class FakeCredential:
    """A TokenCredential handing out numbered tokens, recording each call."""

    def __init__(self, lifetime: float = 3600) -> None:
        self.calls: list[tuple] = []
        self.lifetime = lifetime

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        self.calls.append(scopes)
        return AccessToken(f"token-{len(self.calls)}", int(time.time() + self.lifetime))


# Path templating -----------------------------------------------------------


def test_path_templating_and_encoding(transport):
    transport.add(httpx.Response(204), httpx.Response(204))
    with ApiClient(HOST + "/base") as client:
        client.fetch("/subscriptions/{sub}/rg/{name}", sub="s 1", name="a/b?c#d%")
        client.fetch("plain", query={"api-version": "2021-04-01", "q": "x y"})
    first, second = (r.url for r in transport.requests)
    assert first.raw_path == b"/base/subscriptions/s%201/rg/a%2Fb%3Fc%23d%25"
    assert str(second) == f"{HOST}/base/plain?api-version=2021-04-01&q=x+y"


@pytest.mark.parametrize(
    ("path", "params", "match"),
    [
        ("/a/{x}/{y}", {"x": "1"}, "Missing path parameter.*y"),
        ("/a/{x}", {"x": "1", "z": "2"}, "Unused path parameter.*z"),
        ("/a", {"z": "2"}, "Unused path parameter.*z"),
        ("/a/{}", {}, "must be names"),
        ("/a/{0}", {}, "must be names"),
    ],
)
def test_missing_and_unused_path_parameters(transport, path, params, match):
    with ApiClient(HOST) as client, pytest.raises(ValueError, match=match):
        client.fetch(path, **params)
    assert transport.requests == []


def test_host_url_from_the_class_or_argument(transport):
    class Api(ApiClient):
        host_url = HOST

    transport.add(httpx.Response(204), httpx.Response(204))
    Api().fetch("/x")
    Api("https://other.example.com").fetch("/x")
    assert [str(r.url) for r in transport.requests] == [f"{HOST}/x", "https://other.example.com/x"]
    with pytest.raises(ValueError, match="host_url"):
        ApiClient()


def test_method_json_body_and_headers(transport):
    transport.add(httpx.Response(204))
    with ApiClient(HOST) as client:
        client.fetch("/x", "post", json={"a": [1, None]}, headers={"X-Extra": "1"})
    (req,) = transport.requests
    assert req.method == "POST"
    assert req.body == b'{"a":[1,null]}'
    assert req.headers["content-type"] == "application/json"
    assert req.headers["x-extra"] == "1"
    assert "authorization" not in req.headers  # no credential: unauthenticated


# Parsing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "content_type", "expected"),
    [
        (json_response(200, {"a": [1, 2]}), None, {"a": [1, 2]}),
        (
            httpx.Response(
                200, text="<r><i>1</i></r>", headers={"content-type": "application/xml"}
            ),
            None,
            "r",
        ),
        (
            httpx.Response(200, text="<p>hi</p>", headers={"content-type": "text/html"}),
            None,
            "<p>hi</p>",
        ),
        (httpx.Response(200, text="plain"), None, "plain"),
        (
            httpx.Response(200, text='{"a": 1}', headers={"content-type": "text/plain"}),
            "application/json",
            {"a": 1},
        ),
        (json_response(200, {"a": 1}), "text/plain", '{"a": 1}'),
        (httpx.Response(200, headers={"content-type": "application/json"}), None, None),
        (httpx.Response(204), None, None),
    ],
)
def test_parsing_by_content_type(transport, response, content_type, expected):
    transport.add(response)
    result = ApiClient(HOST).fetch("/x", content_type=content_type)
    if isinstance(result, ET.Element):
        assert result.tag == expected
        assert result.find("i").text == "1"
    else:
        assert result == expected


def test_response_handler(transport):
    seen = []

    def handler(content):
        seen.append(content)
        return ("handled", content)

    transport.add(json_response(200, [1]), httpx.Response(200, text="t"), httpx.Response(204))
    client = ApiClient(HOST, response_handler=handler)
    assert client.fetch("/x") == ("handled", [1])
    assert client.fetch("/x") == ("handled", "t")
    assert client.fetch("/x") is None  # an empty body is not handed to the handler
    assert seen == [[1], "t"]


def test_api_error_message(transport):
    transport.add(json_response(404, {"error": {"code": "NotFound"}}), httpx.Response(500))
    client = ApiClient(HOST)
    with pytest.raises(ApiError) as err:
        client.fetch("/things/{id}", "DELETE", id="7")
    e = err.value
    assert isinstance(e, DazureError)
    assert isinstance(e, httpx.HTTPStatusError)
    assert e.response.status_code == 404
    assert e.request.url == f"{HOST}/things/7"
    assert str(e) == (
        f'DELETE {HOST}/things/7 failed: HTTP 404 Not Found\n{{"error": {{"code": "NotFound"}}}}'
    )
    with pytest.raises(
        ApiError, match=r"^GET https://api.example.com/x failed: HTTP 500 Internal Server Error$"
    ):
        client.fetch("/x")


# Retry ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503])
def test_transient_statuses_are_retried_up_to_max_tries(transport, sleeps, status):
    transport.add(*[httpx.Response(status)] * 3)
    with pytest.raises(ApiError) as err:
        ApiClient(HOST, max_tries=3).fetch("/x", "POST", json={})
    assert err.value.response.status_code == status
    assert len(transport.requests) == 3
    assert len(sleeps) == 2

    transport.add(httpx.Response(status), json_response(200, "ok"))
    assert ApiClient(HOST, max_tries=3).fetch("/x") == "ok"
    assert len(transport.requests) == 5


def test_connection_errors_are_retried(transport, sleeps):
    transport.add(httpx.ConnectError, httpx.ConnectTimeout, json_response(200, "ok"))
    assert ApiClient(HOST, max_tries=3).fetch("/x", "PUT", json={}) == "ok"
    assert len(transport.requests) == 3
    assert len(sleeps) == 2

    transport.add(*[httpx.ConnectError] * 2)
    with pytest.raises(httpx.ConnectError):
        ApiClient(HOST, max_tries=2).fetch("/x")
    assert len(transport.requests) == 5


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(504),
        httpx.ReadTimeout,
        httpx.ReadError,
    ],
)
def test_other_failures_are_sent_once(transport, sleeps, outcome):
    transport.add(outcome)
    with pytest.raises((ApiError, httpx.ReadTimeout, httpx.ReadError)):
        ApiClient(HOST).fetch("/x", "POST", json={"side": "effect"})
    assert len(transport.requests) == 1
    assert sleeps == []


def test_retry_after_is_honoured(transport, sleeps, monkeypatch):
    monkeypatch.setattr(dazure._api_client, "_uniform", lambda a, b: pytest.fail("backoff used"))
    when = email.utils.formatdate(time.time() + 30, usegmt=True)
    transport.add(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503, headers={"Retry-After": "0.5"}),
        httpx.Response(503, headers={"Retry-After": when}),
        httpx.Response(204),
    )
    ApiClient(HOST).fetch("/x")
    assert sleeps[:2] == [7.0, 0.5]
    assert 28 <= sleeps[2] <= 30


def test_backoff_without_retry_after(transport, sleeps, monkeypatch):
    bounds = []

    def uniform(a, b):
        bounds.append((a, b))
        return b  # the top of the range, to see the cap

    monkeypatch.setattr(dazure._api_client, "_uniform", uniform)
    transport.add(httpx.Response(429, headers={"Retry-After": "soon"}), *[httpx.Response(503)] * 5)
    with pytest.raises(ApiError):
        ApiClient(HOST, max_tries=6).fetch("/x")
    assert bounds == [(1.0, 2.5**i) for i in range(1, 6)]
    assert sleeps == [2.5, 6.2, 15.6, 39.1, 60.0]  # round(2.5**i, 1), capped at 60


def test_backoff_default_bounds():
    # azr's backoff_default(): runif(1, min = 1, max = 2.5^i), capped at 60, one decimal.
    import random

    rng = random.Random(42)
    for attempt in range(1, 8):
        for _ in range(200):
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(dazure._api_client, "_uniform", rng.uniform)
                x = backoff_default(attempt)
            assert 1.0 <= x <= min(2.5**attempt, 60.0)
            assert x == round(x, 1)


def test_retry_is_logged_as_a_warning(transport, sleeps, monkeypatch, caplog):
    monkeypatch.setattr(dazure._api_client, "_uniform", lambda a, b: 2.0)
    transport.add(httpx.Response(503), httpx.Response(204))
    with caplog.at_level(logging.WARNING, logger="dazure.http"):
        ApiClient(HOST).fetch("/x")
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "⚠ Request failed. Retrying in 2 secs. (attempt 1 of 5)." in record.getMessage()


# Bearer token ---------------------------------------------------------------------


def test_bearer_token_fetched_once_for_the_scope(transport):
    cred = FakeCredential()
    transport.add(*[httpx.Response(204)] * 3)
    client = ApiClient(HOST, credential=cred)
    for _ in range(3):
        client.fetch("/x")
    assert cred.calls == [(f"{HOST}/.default",)]
    assert [r.headers["authorization"] for r in transport.requests] == ["Bearer token-1"] * 3

    transport.add(httpx.Response(204))
    ApiClient(HOST, credential=cred, scope="api://app/.default").fetch("/x")
    assert cred.calls[-1] == ("api://app/.default",)


def test_bearer_token_renewed_five_minutes_before_expiry(transport, monkeypatch):
    cred = FakeCredential(lifetime=3600)
    now = time.time()
    clock = [now]
    monkeypatch.setattr(dazure._api_client, "_now", lambda: clock[0])
    transport.add(*[httpx.Response(204)] * 3)
    client = ApiClient(HOST, credential=cred)
    client.fetch("/x")
    clock[0] = now + 3600 - 301
    client.fetch("/x")
    clock[0] = now + 3600 - 299
    client.fetch("/x")
    auth = [r.headers["authorization"] for r in transport.requests]
    assert auth == ["Bearer token-1", "Bearer token-1", "Bearer token-2"]


def test_bearer_token_dropped_after_401_and_not_replayed(transport):
    cred = FakeCredential()
    transport.add(httpx.Response(401), httpx.Response(204))
    client = ApiClient(HOST, credential=cred)
    with pytest.raises(ApiError):
        client.fetch("/x")
    assert len(transport.requests) == 1
    client.fetch("/x")
    auth = [r.headers["authorization"] for r in transport.requests]
    assert auth == ["Bearer token-1", "Bearer token-2"]


def test_class_credential_from_app_credential(transport, monkeypatch):
    calls = []
    cred = FakeCredential()

    def fake_app_credential(*args, **kwargs):
        calls.append((args, kwargs))
        return cred

    monkeypatch.setattr(dazure._api_client, "app_credential", fake_app_credential)

    class Api(ApiClient):
        host_url = HOST
        scope = "api://app/.default"
        client_id_env = "APP_ID"
        client_secret_env = "APP_SECRET"
        tenant_id_env = "APP_TENANT"
        mode = "prod"

    transport.add(httpx.Response(204))
    client = Api()
    assert calls == [(("APP_ID", "APP_SECRET"), {"tenant_id_env": "APP_TENANT", "mode": "prod"})]
    assert cred.calls == []  # the first token is fetched lazily
    client.fetch("/x")
    assert cred.calls == [("api://app/.default",)]
    Api(credential=FakeCredential())
    assert len(calls) == 1  # a given credential wins


# Logging -----------------------------------------------------------------------------


def test_logging_in_azr_format(transport, caplog, monkeypatch):
    ticks = iter([10.0, 10.21, 20.0, 20.5])
    monkeypatch.setattr(dazure._api_client, "_clock", lambda: next(ticks))
    transport.add(
        json_response(201, {"id": 1}),
        json_response(500, {"error": {"code": "Boom", "message": "bad"}}),
    )
    client = ApiClient(HOST, credential=FakeCredential(), verbose=True)
    with caplog.at_level(logging.INFO, logger="dazure.http"):
        client.fetch("/x", "POST", json={"name": "rg1", "location": "westeurope"})
        with pytest.raises(ApiError):
            client.fetch("/y")
    messages = [r.getMessage() for r in caplog.records]
    size_ok = f"{9 / 1024:.2f}"  # the 9 bytes of {"id": 1}
    assert messages[:4] == [
        f"{INFO} >>> POST {HOST}/x",
        f"{INFO} >>> body:",
        '{\n  "name": "rg1",\n  "location": "westeurope"\n}',
        f"[green]✔ <<< status = 201 | time = 0.21 secs. | size = {size_ok} Kb[/green]",
    ]
    assert messages[4] == f"{INFO} >>> GET {HOST}/y"
    assert messages[5].startswith("[red]✖ <<< status = 500 | time = 0.5 secs. | size = 0.")
    assert messages[6:] == [
        "[red]✖ <<< body:[/red]",
        '{\n  "error": {\n    "code": "Boom",\n    "message": "bad"\n  }\n}',
    ]
    assert all(r.name == "dazure.http" for r in caplog.records)
    assert not any("token-1" in m or "uthorization" in m for m in messages)


def test_not_verbose_logs_no_requests(transport, caplog):
    transport.add(httpx.Response(204))
    with caplog.at_level(logging.DEBUG, logger="dazure.http"):
        ApiClient(HOST).fetch("/x")
    assert caplog.records == []


def test_verbose_attaches_rich_handler_only_if_none(transport):
    log = logging.getLogger("dazure.http")
    log.handlers.clear()
    log.setLevel(logging.NOTSET)
    ApiClient(HOST, verbose=True)
    ApiClient(HOST, verbose=True)
    (handler,) = log.handlers
    assert isinstance(handler, RichHandler)
    assert log.getEffectiveLevel() == logging.INFO

    own = logging.NullHandler()
    log.handlers[:] = [own]
    ApiClient(HOST, verbose=True)
    assert log.handlers == [own]
    ApiClient(HOST)
    assert log.handlers == [own]


def test_bearer_auth_repr_and_markup_escaped(transport, caplog):
    assert "token" not in repr(BearerAuth(FakeCredential(), "s")).replace("FakeCredential", "")
    transport.add(json_response(400, {"why": "[bold]x[/bold]"}))
    with caplog.at_level(logging.INFO, logger="dazure.http"), pytest.raises(ApiError):
        ApiClient(HOST, verbose=True).fetch("/x", "POST", json={"f": "[red]x[/red]"})
    bodies = [r.getMessage() for r in caplog.records if r.getMessage().startswith("{")]
    # Rich markup in a body is escaped, so it prints as sent.
    assert bodies == ['{\n  "f": "\\[red]x\\[/red]"\n}', '{\n  "why": "\\[bold]x\\[/bold]"\n}']
