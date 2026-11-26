"""ApiClient against the recording transport (design §4.1)."""

from __future__ import annotations

import email.utils
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
from azure.core.credentials import AccessToken
from recording_transport import RecordingTransport, json_response
from rich.logging import RichHandler
from rich.markup import escape

import dazapiz._api_client
from dazapiz import ApiClient, ApiError, DazapizError
from dazapiz._api_client import BearerAuth, _abbreviate_json, backoff_default

INFO = "\N{INFORMATION SOURCE}"
HOST = "https://api.example.com"


@pytest.fixture
def transport() -> RecordingTransport:
    """The transport a test passes as `transport=`, recording what was sent."""
    return RecordingTransport()


@pytest.fixture
def sleeps() -> list[float]:
    """Retries record their waits here instead of sleeping (`sleep=sleeps.append`)."""
    return []


@pytest.fixture(autouse=True)
def _restore_http_logger():
    log = logging.getLogger("dazapiz.http")
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
    with ApiClient(HOST + "/base", transport=transport) as client:
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
    with ApiClient(HOST, transport=transport) as client, pytest.raises(ValueError, match=match):
        client.fetch(path, **params)
    assert transport.requests == []


def test_host_url_from_the_class_or_argument(transport):
    class Api(ApiClient):
        host_url = HOST

    transport.add(httpx.Response(204), httpx.Response(204))
    Api(transport=transport).fetch("/x")
    Api("https://other.example.com", transport=transport).fetch("/x")
    assert [str(r.url) for r in transport.requests] == [f"{HOST}/x", "https://other.example.com/x"]
    with pytest.raises(ValueError, match="host_url"):
        ApiClient()


def test_method_json_body_and_headers(transport):
    transport.add(httpx.Response(204))
    with ApiClient(HOST, transport=transport) as client:
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
    result = ApiClient(HOST, transport=transport).fetch("/x", content_type=content_type)
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
    client = ApiClient(HOST, transport=transport, response_handler=handler)
    assert client.fetch("/x") == ("handled", [1])
    assert client.fetch("/x") == ("handled", "t")
    assert client.fetch("/x") is None  # an empty body is not handed to the handler
    assert seen == [[1], "t"]


def test_api_error_message(transport):
    transport.add(json_response(404, {"error": {"code": "NotFound"}}), httpx.Response(500))
    client = ApiClient(HOST, transport=transport)
    with pytest.raises(ApiError) as err:
        client.fetch("/things/{id}", "DELETE", id="7")
    e = err.value
    assert isinstance(e, DazapizError)
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
        ApiClient(HOST, transport=transport, sleep=sleeps.append, max_tries=3).fetch(
            "/x", "POST", json={}
        )
    assert err.value.response.status_code == status
    assert len(transport.requests) == 3
    assert len(sleeps) == 2

    transport.add(httpx.Response(status), json_response(200, "ok"))
    assert (
        ApiClient(HOST, transport=transport, sleep=sleeps.append, max_tries=3).fetch("/x") == "ok"
    )
    assert len(transport.requests) == 5


def test_connection_errors_are_retried(transport, sleeps):
    transport.add(httpx.ConnectError, httpx.ConnectTimeout, json_response(200, "ok"))
    assert (
        ApiClient(HOST, transport=transport, sleep=sleeps.append, max_tries=3).fetch(
            "/x", "PUT", json={}
        )
        == "ok"
    )
    assert len(transport.requests) == 3
    assert len(sleeps) == 2

    transport.add(*[httpx.ConnectError] * 2)
    with pytest.raises(httpx.ConnectError):
        ApiClient(HOST, transport=transport, sleep=sleeps.append, max_tries=2).fetch("/x")
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
        ApiClient(HOST, transport=transport, sleep=sleeps.append).fetch(
            "/x", "POST", json={"side": "effect"}
        )
    assert len(transport.requests) == 1
    assert sleeps == []


def test_retry_after_is_honoured(transport, sleeps, monkeypatch):
    monkeypatch.setattr(dazapiz._api_client, "_uniform", lambda a, b: pytest.fail("backoff used"))
    when = email.utils.formatdate(time.time() + 30, usegmt=True)
    transport.add(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503, headers={"Retry-After": "0.5"}),
        httpx.Response(503, headers={"Retry-After": when}),
        httpx.Response(204),
    )
    ApiClient(HOST, transport=transport, sleep=sleeps.append).fetch("/x")
    assert sleeps[:2] == [7.0, 0.5]
    assert 28 <= sleeps[2] <= 30


def test_backoff_without_retry_after(transport, sleeps, monkeypatch):
    bounds = []

    def uniform(a, b):
        bounds.append((a, b))
        return b  # the top of the range, to see the cap

    monkeypatch.setattr(dazapiz._api_client, "_uniform", uniform)
    transport.add(httpx.Response(429, headers={"Retry-After": "soon"}), *[httpx.Response(503)] * 5)
    with pytest.raises(ApiError):
        ApiClient(HOST, transport=transport, sleep=sleeps.append, max_tries=6).fetch("/x")
    assert bounds == [(1.0, 2.5**i) for i in range(1, 6)]
    assert sleeps == [2.5, 6.2, 15.6, 39.1, 60.0]  # round(2.5**i, 1), capped at 60


def test_backoff_default_bounds():
    # azr's backoff_default(): runif(1, min = 1, max = 2.5^i), capped at 60, one decimal.
    import random

    rng = random.Random(42)
    for attempt in range(1, 8):
        for _ in range(200):
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(dazapiz._api_client, "_uniform", rng.uniform)
                x = backoff_default(attempt)
            assert 1.0 <= x <= min(2.5**attempt, 60.0)
            assert x == round(x, 1)


def test_retry_is_logged_as_a_warning(transport, sleeps, monkeypatch, caplog):
    monkeypatch.setattr(dazapiz._api_client, "_uniform", lambda a, b: 2.0)
    transport.add(httpx.Response(503), httpx.Response(204))
    with caplog.at_level(logging.WARNING, logger="dazapiz.http"):
        ApiClient(HOST, transport=transport, sleep=sleeps.append).fetch("/x")
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "⚠ Request failed. Retrying in 2 secs. (attempt 1 of 5)." in record.getMessage()


# Bearer token ---------------------------------------------------------------------


def test_bearer_token_fetched_once_for_the_scope(transport):
    cred = FakeCredential()
    transport.add(*[httpx.Response(204)] * 3)
    client = ApiClient(HOST, transport=transport, credential=cred)
    for _ in range(3):
        client.fetch("/x")
    assert cred.calls == [(f"{HOST}/.default",)]
    assert [r.headers["authorization"] for r in transport.requests] == ["Bearer token-1"] * 3

    transport.add(httpx.Response(204))
    ApiClient(HOST, transport=transport, credential=cred, scope="api://app/.default").fetch("/x")
    assert cred.calls[-1] == ("api://app/.default",)


def test_bearer_token_renewed_five_minutes_before_expiry(transport, monkeypatch):
    cred = FakeCredential(lifetime=3600)
    now = time.time()
    clock = [now]
    monkeypatch.setattr(dazapiz._api_client, "_now", lambda: clock[0])
    transport.add(*[httpx.Response(204)] * 3)
    client = ApiClient(HOST, transport=transport, credential=cred)
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
    client = ApiClient(HOST, transport=transport, credential=cred)
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

    monkeypatch.setattr(dazapiz._api_client, "app_credential", fake_app_credential)

    class Api(ApiClient):
        host_url = HOST
        scope = "api://app/.default"
        client_id_env = "APP_ID"
        client_secret_env = "APP_SECRET"
        tenant_id_env = "APP_TENANT"
        mode = "prod"

    transport.add(httpx.Response(204))
    client = Api(transport=transport)
    assert calls == [(("APP_ID", "APP_SECRET"), {"tenant_id_env": "APP_TENANT", "mode": "prod"})]
    assert cred.calls == []  # the first token is fetched lazily
    client.fetch("/x")
    assert cred.calls == [("api://app/.default",)]
    Api(credential=FakeCredential())
    assert len(calls) == 1  # a given credential wins


# Logging -----------------------------------------------------------------------------


def test_logging_in_azr_format(transport, caplog, monkeypatch):
    ticks = iter([10.0, 10.21, 20.0, 20.5])
    monkeypatch.setattr(dazapiz._api_client, "_clock", lambda: next(ticks))
    transport.add(
        json_response(201, {"id": 1}),
        json_response(500, {"error": {"code": "Boom", "message": "bad"}}),
    )
    client = ApiClient(HOST, transport=transport, credential=FakeCredential(), verbose=True)
    with caplog.at_level(logging.INFO, logger="dazapiz.http"):
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
    assert all(r.name == "dazapiz.http" for r in caplog.records)
    assert not any("token-1" in m or "uthorization" in m for m in messages)


def test_not_verbose_logs_no_requests(transport, caplog):
    transport.add(httpx.Response(204))
    with caplog.at_level(logging.DEBUG, logger="dazapiz.http"):
        ApiClient(HOST, transport=transport).fetch("/x")
    assert caplog.records == []


def test_verbose_attaches_rich_handler_only_if_none(transport):
    log = logging.getLogger("dazapiz.http")
    log.handlers.clear()
    log.setLevel(logging.NOTSET)
    ApiClient(HOST, transport=transport, verbose=True)
    ApiClient(HOST, transport=transport, verbose=True)
    (handler,) = log.handlers
    assert isinstance(handler, RichHandler)
    assert log.getEffectiveLevel() == logging.INFO

    own = logging.NullHandler()
    log.handlers[:] = [own]
    ApiClient(HOST, transport=transport, verbose=True)
    assert log.handlers == [own]
    ApiClient(HOST, transport=transport)
    assert log.handlers == [own]


def test_bearer_auth_repr_and_markup_escaped(transport, caplog):
    assert "token" not in repr(BearerAuth(FakeCredential(), "s")).replace("FakeCredential", "")
    transport.add(json_response(400, {"why": "[bold]x[/bold]"}))
    with caplog.at_level(logging.INFO, logger="dazapiz.http"), pytest.raises(ApiError):
        ApiClient(HOST, transport=transport, verbose=True).fetch(
            "/x", "POST", json={"f": "[red]x[/red]"}
        )
    bodies = [r.getMessage() for r in caplog.records if r.getMessage().startswith("{")]
    # Rich markup in a body is escaped, so it prints as sent.
    assert bodies == ['{\n  "f": "\\[red]x\\[/red]"\n}', '{\n  "why": "\\[bold]x\\[/bold]"\n}']


# Abbreviated JSON bodies (design §4.1, #22) ---------------------------------------
#
# The oracle is `tests/fixtures/azr_json_body.json`, written by
# `tools/azr_json_body_fixture.R` from azr's `format_json_body()`.

AZR_BODIES = json.loads(
    (Path(__file__).parent / "fixtures" / "azr_json_body.json").read_text(encoding="utf-8")
)
# Cases where jsonlite coerces an atomic vector's scalars to strings: a number,
# boolean or null in a truncated or mixed array prints as "1", "TRUE" or "NA".
# For these cases only, azr's text is normalised by unquoting quoted numerals,
# "TRUE", "FALSE" and "NA" (to true, false, null). Their inputs hold no string
# that looks like one, so the normalisation cannot hide a real difference.
JSONLITE_COERCES = {
    "atomic_numbers_13",
    "atomic_booleans_13",
    "atomic_numbers_with_null",
    "atomic_mixed",
}
_COERCED = re.compile(r'"(-?\d+(?:\.\d+)?|TRUE|FALSE|NA)"')
_UNCOERCE = {"TRUE": "true", "FALSE": "false", "NA": "null"}


def _uncoerce(text: str) -> str:
    return _COERCED.sub(lambda m: _UNCOERCE.get(m[1], m[1]), text)


def test_azr_fixture_is_from_a_clean_checkout():
    assert AZR_BODIES["generator"] == "tools/azr_json_body_fixture.R"
    assert re.fullmatch(r"[0-9a-f]{40}", AZR_BODIES["azr_commit"])
    assert AZR_BODIES["azr_dirty"] is False
    assert len(AZR_BODIES["cases"]) >= 20


@pytest.mark.parametrize("case", AZR_BODIES["cases"], ids=lambda c: c["id"])
def test_abbreviate_json_matches_azr(case):
    expected = case["azr"]
    if case["id"] in JSONLITE_COERCES:
        expected = _uncoerce(expected)
    assert _abbreviate_json(json.loads(case["input"])) == expected


def test_abbreviate_json_object_boundary():
    ten = {f"k{i}": i for i in range(10)}
    assert _abbreviate_json(ten) == json.dumps(ten, indent=2)
    eleven = {f"k{i}": i for i in range(11)}
    lines = _abbreviate_json(eleven).splitlines()
    assert lines[1:6] == [f'  "k{i}": {i},' for i in range(5)]
    assert lines[6] == "  ...,"
    assert lines[7:12] == [f'  "k{i}": {i},' for i in range(6, 10)] + ['  "k10": 10']
    assert "k5" not in _abbreviate_json(eleven)


def test_abbreviate_json_array_boundary():
    assert _abbreviate_json([{"a": i} for i in range(10)]).count("{") == 10
    eleven = _abbreviate_json([{"a": i} for i in range(11)])
    assert eleven.count("{") == 10
    assert '"a": 5' not in eleven
    assert "  ...," in eleven


def test_abbreviate_json_atomic_boundary():
    twelve = _abbreviate_json({"x": list(range(12))})
    assert twelve == '{\n  "x": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]\n}'
    thirteen = _abbreviate_json({"x": list(range(13))})
    assert thirteen == '{\n  "x": [0, 1, 2, 3, 4, 5, ..., 7, 8, 9, 10, 11, 12]\n}'


def test_abbreviate_json_keeps_scalars_and_ellipsis_strings():
    # Unlike azr, a top-level scalar is not boxed and a "..." string stays quoted.
    assert _abbreviate_json(5) == "5"
    assert _abbreviate_json(None) == "null"
    assert _abbreviate_json({"x": [5], "s": "..."}) == '{\n  "x": [5],\n  "s": "..."\n}'


def test_logged_bodies_are_abbreviated(transport, caplog):
    transport.add(json_response(400, {"error": {"details": list(range(13))}}))
    client = ApiClient(HOST, transport=transport, verbose=True)
    body = {f"k{i:02d}": [str(j) for j in range(13)] for i in range(11)}
    with caplog.at_level(logging.INFO, logger="dazapiz.http"), pytest.raises(ApiError):
        client.fetch("/x", "POST", json=body)
    messages = [r.getMessage() for r in caplog.records]
    sent = messages[messages.index(f"{INFO} >>> body:") + 1]
    assert sent == _abbreviate_json(body)
    assert sent.count("...") == 1 + 10  # the object, and each kept array
    assert '"k05"' not in sent
    failed = messages[messages.index("[red]✖ <<< body:[/red]") + 1]
    assert (
        failed
        == '{\n  "error": {\n    "details": [0, 1, 2, 3, 4, 5, ..., 7, 8, 9, 10, 11, 12]\n  }\n}'
    )


def test_logged_non_json_bodies_are_unchanged(transport, caplog):
    text = "[" + ", ".join(["x"] * 50)  # long, and not valid JSON
    transport.add(
        httpx.Response(500, text=text, headers={"content-type": "text/plain"}),
        httpx.Response(500, text=text, headers={"content-type": "application/json"}),
    )
    client = ApiClient(HOST, transport=transport, verbose=True)
    with caplog.at_level(logging.INFO, logger="dazapiz.http"):
        for _ in range(2):
            with pytest.raises(ApiError):
                client.fetch("/x")
    bodies = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[x")]
    assert bodies == [escape(text)] * 2


@pytest.mark.parametrize("bad", [0, -1, 1.5, "3"])
def test_max_tries_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError, match="max_tries"):
        ApiClient(HOST, max_tries=bad)


# Public test hooks: transport=, sleep=, .credential --------------------------------


def test_transport_argument_carries_the_requests():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    with ApiClient(HOST, transport=httpx.MockTransport(handler)) as client:
        assert client.fetch("/x") == {"ok": True}
    assert [str(r.url) for r in seen] == [HOST + "/x"]


def test_sleep_argument_receives_the_retry_waits():
    waits: list[float] = []
    transport = RecordingTransport()
    transport.add(httpx.Response(429, headers={"Retry-After": "7"}), json_response(200, "ok"))
    client = ApiClient(HOST, transport=transport, sleep=waits.append)
    assert client.fetch("/x") == "ok"
    assert waits == [7.0]


def test_sleep_defaults_to_time_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    transport = RecordingTransport()
    transport.add(httpx.Response(503, headers={"Retry-After": "0.5"}), httpx.Response(204))
    ApiClient(HOST, transport=transport).fetch("/x")
    assert waits == [0.5]


def test_credential_property():
    cred = FakeCredential()
    assert ApiClient(HOST, credential=cred).credential is cred
    assert ApiClient(HOST).credential is None
    with pytest.raises(AttributeError):
        ApiClient(HOST).credential = cred  # type: ignore[misc]


def test_credential_property_is_the_one_app_credential_chose(monkeypatch):
    monkeypatch.delenv("AZURE_TOKEN_CREDENTIALS", raising=False)
    monkeypatch.setenv("T_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("T_SECRET", "s")
    monkeypatch.setenv("AZURE_TENANT_ID", "00000000-0000-0000-0000-000000000002")

    class Client(ApiClient):
        host_url = HOST
        client_id_env = "T_ID"
        client_secret_env = "T_SECRET"

    from azure.identity import ClientSecretCredential

    assert isinstance(Client().credential, ClientSecretCredential)
