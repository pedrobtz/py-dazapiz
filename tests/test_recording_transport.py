"""The recording transport of tests/recording_transport.py."""

import httpx
import pytest
from recording_transport import RecordingTransport, json_response


def test_records_whole_requests_and_serves_the_script_in_turn():
    transport = RecordingTransport([httpx.Response(201, text="one"), json_response(200, [1])])
    with httpx.Client(transport=transport, base_url="https://h.example") as client:
        first = client.post("/a?x=1", json={"k": "v"}, headers={"X-Test": "t"})
        second = client.get("/b")
    assert (first.status_code, first.text) == (201, "one")
    assert second.json() == [1]
    a, b = transport.requests
    assert (a.method, str(a.url), a.body) == ("POST", "https://h.example/a?x=1", b'{"k":"v"}')
    assert a.headers["x-test"] == "t"
    assert a.headers["content-type"] == "application/json"
    assert (b.method, str(b.url), b.body) == ("GET", "https://h.example/b", b"")


def test_raises_scripted_exceptions_with_the_request():
    transport = RecordingTransport([httpx.ConnectError, httpx.ReadTimeout("slow"), ValueError])
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.ConnectError) as err:
            client.get("https://h.example/1")
        assert err.value.request.url == "https://h.example/1"
        with pytest.raises(httpx.ReadTimeout) as err:
            client.get("https://h.example/2")
        assert err.value.request.url == "https://h.example/2"
        with pytest.raises(ValueError):
            client.get("https://h.example/3")
    assert len(transport.requests) == 3


def test_a_request_past_the_script_fails():
    transport = RecordingTransport([httpx.Response(200)])
    transport.add(httpx.Response(204))
    with httpx.Client(transport=transport) as client:
        assert client.get("https://h.example/").status_code == 200
        assert client.get("https://h.example/").status_code == 204
        with pytest.raises(AssertionError, match="unscripted request: GET"):
            client.get("https://h.example/")
