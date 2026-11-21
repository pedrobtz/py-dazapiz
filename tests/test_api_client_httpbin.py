"""`ApiClient` over real HTTP, against a local httpbin (design §4.1, §8.1).

`pytest-httpbin` serves httpbin on a loopback port, so these requests go
through httpx's own transport and a real socket: what httpbin echoes is
what arrived on the wire. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET

import httpx
import pytest
from azure.core.credentials import AccessToken
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from dazure import ApiClient, ApiError

TOKEN = "httpbin-bearer-sentinel-91c4"
STATUS = re.compile(
    r"<<< status = (\d+) \| time = (\d+(?:\.\d+)?(?:e-?\d+)?) secs\. \| size = (\d+\.\d\d) Kb"
)


class FakeCredential:
    def __init__(self) -> None:
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        self.scopes.append(scopes)
        return AccessToken(TOKEN, int(time.time()) + 3600)


class Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    display_name: str
    note: str | None = None


@pytest.fixture
def no_sleep() -> list[float]:
    """Retry waits, recorded instead of slept (`sleep=no_sleep.append`)."""
    return []


@pytest.fixture(autouse=True)
def _restore_http_logger():
    log = logging.getLogger("dazure.http")
    handlers, level = list(log.handlers), log.level
    yield
    log.handlers[:] = handlers
    log.setLevel(level)


def messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "dazure.http"]


# Bearer token --------------------------------------------------------------------------


def test_bearer_token_arrives(httpbin):
    cred = FakeCredential()
    with ApiClient(httpbin.url, credential=cred, scope="api://test/.default") as client:
        assert client.fetch("/bearer") == {"authenticated": True, "token": TOKEN}
    assert cred.scopes == [("api://test/.default",)]


def test_no_credential_no_bearer(httpbin):
    with ApiClient(httpbin.url) as client, pytest.raises(ApiError) as err:
        client.fetch("/bearer")
    assert err.value.response.status_code == 401
    assert "authorization" not in err.value.request.headers


# What arrives ----------------------------------------------------------------------------


def _request_lines(capsys, prefix: str, timeout: float = 5.0) -> list[str]:
    """The request lines starting with `prefix` that wsgiref logged to stderr.

    The server thread logs a request after sending its response, so the line
    can come after the client has its answer (it is waited for here), and a
    previous test's line can arrive in this test's capture (it is filtered).
    """
    err, deadline = "", time.monotonic() + timeout
    while True:
        err += capsys.readouterr().err
        lines = re.findall(r'"([A-Z]+ \S+ HTTP/1\.1)"', err)
        found = [line for line in lines if line.startswith(prefix)]
        if found or time.monotonic() > deadline:
            return found
        time.sleep(0.01)


def test_path_parameters_arrive_encoded(httpbin, capsys):
    with ApiClient(httpbin.url) as client:
        echo = client.fetch("/anything/{a}/{b}", a="a b/c?d#e", b="ü%")
    # The request line as the server read it: every reserved character
    # percent-encoded, so each value stays one segment.
    assert _request_lines(capsys, "GET /anything/") == [
        "GET /anything/a%20b%2Fc%3Fd%23e/%C3%BC%25 HTTP/1.1"
    ]
    # httpbin decodes the path (%2F included) before echoing it; nothing went to
    # the query or the fragment.
    assert echo["url"].endswith("/anything/a%20b/c%3Fd%23e/ü%")
    assert echo["args"] == {}


def test_query_arrives(httpbin):
    with ApiClient(httpbin.url) as client:
        echo = client.fetch("/anything", query={"q": "a b&c", "n": [1, 2]})
    assert echo["args"] == {"q": "a b&c", "n": ["1", "2"]}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"name": "rg1", "tags": {"ü": [1, None, True]}}, None),
        (Body(display_name="d"), {"displayName": "d"}),
        (Body(display_name="d", note=None), {"displayName": "d", "note": None}),
    ],
    ids=["dict", "model", "model-explicit-none"],
)
def test_json_body_arrives_as_sent(httpbin, body, expected):
    with ApiClient(httpbin.url) as client:
        echo = client.fetch("/anything", "POST", json=body)
    assert echo["method"] == "POST"
    assert echo["headers"]["Content-Type"] == "application/json"
    assert echo["json"] == (body if expected is None else expected)
    assert json.loads(echo["data"]) == echo["json"]


# Parsing by content type ------------------------------------------------------------------


def test_json_xml_html_and_204(httpbin):
    with ApiClient(httpbin.url) as client:
        assert client.fetch("/json")["slideshow"]["title"] == "Sample Slide Show"
        xml = client.fetch("/xml")
        assert isinstance(xml, ET.Element)
        assert xml.tag == "slideshow"
        html = client.fetch("/html")
        assert isinstance(html, str)
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert client.fetch("/status/204") is None
        assert client.fetch("/status/204", parse=lambda body: ("parsed", body)) == (
            "parsed",
            None,
        )


# Retries ----------------------------------------------------------------------------------


def retry_warnings(caplog) -> list[str]:
    return [m for m in messages(caplog) if "Request failed. Retrying" in m]


@pytest.mark.parametrize("status", [429, 503])
def test_transient_statuses_are_retried(httpbin, caplog, no_sleep, status):
    with (
        ApiClient(httpbin.url, sleep=no_sleep.append, max_tries=3) as client,
        caplog.at_level(logging.WARNING),
        pytest.raises(ApiError) as err,
    ):
        client.fetch(f"/status/{status}", "POST", json={})
    assert err.value.response.status_code == status
    warnings = retry_warnings(caplog)
    assert len(warnings) == 2  # three attempts, two waits
    assert [w.split("(attempt ")[1] for w in warnings] == ["1 of 3).[/yellow]", "2 of 3).[/yellow]"]
    assert len(no_sleep) == 2


def test_500_is_not_retried(httpbin, caplog, no_sleep):
    with (
        ApiClient(httpbin.url, sleep=no_sleep.append, max_tries=3) as client,
        caplog.at_level(logging.INFO),
        pytest.raises(ApiError) as err,
    ):
        client.fetch("/status/500", "POST", json={})
    assert err.value.response.status_code == 500
    assert retry_warnings(caplog) == []
    assert no_sleep == []


def test_read_timeout_is_not_resent(httpbin, caplog, no_sleep):
    client = ApiClient(httpbin.url, sleep=no_sleep.append, timeout=0.5, max_tries=3, verbose=True)
    with client, caplog.at_level(logging.INFO), pytest.raises(httpx.ReadTimeout):
        client.fetch("/delay/2", "POST", json={"once": True})
    sent = [m for m in messages(caplog) if ">>> POST" in m]
    assert len(sent) == 1  # one request left; the server may have acted on it
    assert retry_warnings(caplog) == []
    assert no_sleep == []


# Logging -----------------------------------------------------------------------------------


def test_log_records_have_timing_and_size_but_no_authorization(httpbin, caplog):
    with (
        ApiClient(httpbin.url, credential=FakeCredential(), verbose=True) as client,
        caplog.at_level(logging.INFO),
    ):
        body = client.fetch("/range/{n}", n="2048")  # 2048 ASCII letters
        client.fetch("/anything", "POST", json={"k": "v"})
        with pytest.raises(ApiError):
            client.fetch("/status/418")
    logged = messages(caplog)
    statuses = [m for m in (STATUS.search(m) for m in logged) if m]
    assert [s.group(1) for s in statuses] == ["200", "200", "418"]
    assert len(body) == 2048
    assert statuses[0].group(3) == "2.00"
    assert all(float(s.group(2)) >= 0 for s in statuses)
    # The echo of /anything carries the Authorization header back in its body,
    # but a successful response body is not logged, and headers never are.
    text = "\n".join(logged)
    assert TOKEN not in text
    assert "uthorization" not in text
    assert "Bearer" not in text
