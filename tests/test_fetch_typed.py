"""`fetch(parse=...)` and model bodies for `json=` (design §4.1, D49 to D52, D54)."""

from __future__ import annotations

import dataclasses
import json
import logging
import xml.etree.ElementTree as ET

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel
from recording_transport import RecordingTransport, json_response

import dazapiz._api_client
from dazapiz import ApiClient, ApiError, DazapizError, ResponseParseError

HOST = "https://api.example.com"
INFO = "\N{INFORMATION SOURCE}"
SENTINEL = "body-sentinel-6d1f"


@pytest.fixture
def transport() -> RecordingTransport:
    """Passed as `transport=`; records what was sent."""
    return RecordingTransport()


@pytest.fixture(autouse=True)
def _restore_http_logger():
    log = logging.getLogger("dazapiz.http")
    handlers, level = list(log.handlers), log.level
    yield
    log.handlers[:] = handlers
    log.setLevel(level)


class Thing(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, frozen=True)

    thing_id: int
    display_name: str
    photo_urls: list[str] = Field(default_factory=list)
    note: str | None = None


@dataclasses.dataclass
class Point:
    x_value: int
    label: str | None = None
    tags: list[str] = dataclasses.field(default_factory=list)


# parse= ----------------------------------------------------------------------------


def test_parse_is_applied_after_content_type_parsing(transport):
    seen = []

    def parse(content):
        seen.append(content)
        return ("parsed", content)

    transport.add(
        json_response(200, {"a": [1, 2]}),
        httpx.Response(200, text="plain"),
        httpx.Response(200, content=b"<r><i>1</i></r>", headers={"content-type": "text/xml"}),
    )
    client = ApiClient(HOST, transport=transport)
    assert client.fetch("/x", parse=parse) == ("parsed", {"a": [1, 2]})
    assert client.fetch("/x", parse=parse) == ("parsed", "plain")
    # content_type still decides the parsing parse= receives.
    result = client.fetch("/x", content_type="application/xml", parse=parse)
    assert result[1].tag == "r"
    assert seen[:2] == [{"a": [1, 2]}, "plain"]


def test_parse_with_a_pydantic_model(transport):
    transport.add(json_response(200, {"thingId": 3, "displayName": "n", "extra": True}))
    thing = ApiClient(HOST, transport=transport).fetch(
        "/things/{id}", id="3", parse=Thing.model_validate
    )
    assert thing == Thing(thing_id=3, display_name="n")
    assert transport.requests[0].url == f"{HOST}/things/3"


def test_parse_replaces_response_handler_for_that_call_only(transport):
    handled = []

    def handler(content):
        handled.append(content)
        return "handled"

    transport.add(json_response(200, [1]), json_response(200, [2]))
    client = ApiClient(HOST, transport=transport, response_handler=handler)
    assert client.fetch("/x", parse=lambda c: ("parsed", c)) == ("parsed", [1])
    assert handled == []  # not called before, after, or instead of parse=
    assert client.fetch("/x") == "handled"
    assert handled == [[2]]


def test_parse_gets_none_for_an_empty_body(transport):
    # D50: unlike response_handler (D41), parse= sees every 2xx body, an empty
    # one as None, so fetch(..., parse=f) always returns what f returns.
    seen = []
    transport.add(httpx.Response(204), httpx.Response(200, content=b""), httpx.Response(204))
    client = ApiClient(
        HOST, transport=transport, response_handler=lambda c: pytest.fail("handler called")
    )
    assert client.fetch("/x", "DELETE", parse=lambda c: seen.append(c) or "none-seen") == (
        "none-seen"
    )
    assert client.fetch("/x", parse=lambda c: seen.append(c) or "none-seen") == "none-seen"
    assert seen == [None, None]
    # A model that needs a body fails, rather than None typed as the model.
    with pytest.raises(ResponseParseError) as err:
        client.fetch("/x", parse=Thing.model_validate)
    assert isinstance(err.value.__cause__, ValidationError)


def test_parse_error_is_wrapped_naming_method_and_url_not_the_body(transport):
    body = {"thingId": SENTINEL, "displayName": "n"}  # the bad value is quoted by pydantic
    transport.add(json_response(200, body, headers={"x-secret": SENTINEL}))
    client = ApiClient(HOST, transport=transport)
    with pytest.raises(ResponseParseError) as err:
        client.fetch("/things/{id}", "post", id="a b", query={"q": "1"}, parse=Thing.model_validate)
    e = err.value
    assert isinstance(e, DazapizError)
    assert not isinstance(e, ApiError)  # the request succeeded; its body did not parse
    assert str(e) == (
        f"POST {HOST}/things/a%20b?q=1: the response body was rejected by parse= (ValidationError)."
    )
    assert SENTINEL not in str(e)
    assert isinstance(e.__cause__, ValidationError)
    assert SENTINEL in str(e.__cause__)  # the original keeps its detail
    assert e.response.status_code == 200
    assert e.request.method == "POST"
    assert len(transport.requests) == 1  # not retried


def test_any_exception_from_parse_is_wrapped(transport):
    original = KeyError("missing")

    def parse(content):
        raise original

    transport.add(json_response(200, {}))
    with pytest.raises(ResponseParseError, match=r"^GET .*/x: .*\(KeyError\)\.$") as err:
        ApiClient(HOST, transport=transport).fetch("/x", parse=parse)
    assert err.value.__cause__ is original


def test_parse_is_not_called_on_an_error_response(transport):
    transport.add(json_response(404, {"error": "nope"}))
    with pytest.raises(ApiError):
        ApiClient(HOST, transport=transport).fetch(
            "/x", parse=lambda c: pytest.fail("parse called")
        )


def test_parse_is_not_a_path_parameter(transport):
    transport.add(httpx.Response(204))
    with pytest.raises(ValueError, match="Missing path parameter"):
        ApiClient(HOST, transport=transport).fetch("/x/{parse}", parse=lambda c: c)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("content_type", "body", "media", "cause"),
    [
        (
            "application/json; charset=utf-8",
            b'{"secret": "' + SENTINEL.encode(),
            "application/json",
            json.JSONDecodeError,
        ),
        (
            "application/json",
            b"Pet deleted " + SENTINEL.encode(),
            "application/json",
            json.JSONDecodeError,
        ),
        ("application/json", b'"\xff' + SENTINEL.encode() + b'"', "application/json", ValueError),
        (
            "application/xml",
            b"<a><b>" + SENTINEL.encode() + b"</a>",
            "application/xml",
            ET.ParseError,
        ),
    ],
    ids=["truncated-json", "text-labelled-json", "not-utf8-json", "bad-xml"],
)
def test_content_that_does_not_parse_is_a_parse_error(transport, content_type, body, media, cause):
    # (#26) A body whose content type says JSON or XML but does not parse is a
    # ResponseParseError, not the parser's own exception; the body stays out.
    transport.add(httpx.Response(200, content=body, headers={"content-type": content_type}))
    client = ApiClient(
        HOST, transport=transport, response_handler=lambda c: pytest.fail("handler called")
    )
    with pytest.raises(ResponseParseError) as err:
        client.fetch("/x/{id}", "delete", id="7", parse=lambda c: pytest.fail("parse called"))
    e = err.value
    assert str(e) == (
        f"DELETE {HOST}/x/7: the response body is not valid {media} ({type(e.__cause__).__name__})."
    )
    assert isinstance(e.__cause__, cause)
    assert SENTINEL not in str(e)
    assert e.response.content == body
    assert len(transport.requests) == 1


def test_content_type_override_also_wraps_parse_failures(transport):
    transport.add(httpx.Response(200, text="<html>", headers={"content-type": "text/html"}))
    with pytest.raises(ResponseParseError, match=r"not valid application/xml \(ParseError\)\.$"):
        ApiClient(HOST, transport=transport).fetch("/x", content_type="application/xml")


def test_text_content_type_avoids_the_json_parse(transport):
    # The Petstore labels its plain-text DELETE reply as JSON; content_type= reads it as text.
    transport.add(
        httpx.Response(200, content=b"Pet deleted", headers={"content-type": "application/json"})
    )
    assert (
        ApiClient(HOST, transport=transport).fetch("/x", "DELETE", content_type="text/plain")
        == "Pet deleted"
    )


# json= models ----------------------------------------------------------------------


def test_json_pydantic_model_is_sent_by_alias_without_unset_fields(transport):
    transport.add(httpx.Response(204), httpx.Response(204))
    client = ApiClient(HOST, transport=transport)
    client.fetch("/things", "POST", json=Thing(thing_id=1, display_name="a"))
    # An explicit None is set, so it is sent: exclude_unset, not exclude_none (D51).
    client.fetch("/things", "POST", json=Thing(thing_id=2, display_name="b", note=None))
    first, second = transport.requests
    assert json.loads(first.body) == {"thingId": 1, "displayName": "a"}
    assert json.loads(second.body) == {"thingId": 2, "displayName": "b", "note": None}
    assert first.headers["content-type"] == "application/json"


def test_json_pydantic_model_uses_json_mode(transport):
    from datetime import date

    class Dated(BaseModel):
        on: date
        url: str

    transport.add(httpx.Response(204))
    ApiClient(HOST, transport=transport).fetch(
        "/d", "PUT", json=Dated(on=date(2026, 11, 21), url="u")
    )
    assert json.loads(transport.requests[0].body) == {"on": "2026-11-21", "url": "u"}


def test_json_dataclass_is_sent_as_asdict(transport):
    transport.add(httpx.Response(204))
    ApiClient(HOST, transport=transport).fetch("/p", "POST", json=Point(x_value=1, tags=["t"]))
    assert json.loads(transport.requests[0].body) == {"x_value": 1, "label": None, "tags": ["t"]}


@pytest.mark.parametrize(
    "body",
    [{"a": 1}, [1, 2], "s", 3, None],
    ids=["dict", "list", "str", "int", "none"],
)
def test_json_other_values_are_unchanged(transport, body):
    transport.add(httpx.Response(204))
    ApiClient(HOST, transport=transport).fetch("/o", "POST", json=body)
    sent = transport.requests[0].body
    if body is None:
        assert sent == b""  # json=None sends no body, as before
    else:
        assert json.loads(sent) == body


def test_json_models_nested_in_lists_tuples_and_dicts(transport):
    transport.add(httpx.Response(204), httpx.Response(204), httpx.Response(204))
    client = ApiClient(HOST, transport=transport)
    client.fetch("/l", "POST", json=[Thing(thing_id=1, display_name="a"), Point(x_value=2), 3])
    client.fetch(
        "/d",
        "POST",
        json={
            "thing_key": Thing(thing_id=1, display_name="a", note=None),
            "nested": {"items": (Thing(thing_id=2, display_name="b"), "s")},
            "point": Point(x_value=1, label="p"),
            "plain": [1, {"k": None}],
        },
    )
    client.fetch("/p", "POST", json=Point(x_value=1, tags=[Thing(thing_id=3, display_name="c")]))
    lists, dicts, dataclass = (json.loads(r.body) for r in transport.requests)
    assert lists == [
        {"thingId": 1, "displayName": "a"},
        {"x_value": 2, "label": None, "tags": []},
        3,
    ]
    # Dict keys are left alone (not aliased); values are converted with the same options.
    assert dicts == {
        "thing_key": {"thingId": 1, "displayName": "a", "note": None},
        "nested": {"items": [{"thingId": 2, "displayName": "b"}, "s"]},
        "point": {"x_value": 1, "label": "p", "tags": []},
        "plain": [1, {"k": None}],
    }
    # A model in a dataclass field is dumped too.
    assert dataclass == {"x_value": 1, "label": None, "tags": [{"thingId": 3, "displayName": "c"}]}


def test_dict_keys_are_left_alone():
    # A key could only be converted into an unhashable dict; keys are never touched.
    # (A non-string key cannot be sent as JSON anyway, so this is checked on the converter.)
    @dataclasses.dataclass(frozen=True)
    class Key:
        k: int

    key = Key(1)
    converted = dazapiz._api_client._to_json({key: Point(x_value=1), (1, 2): [Point(x_value=2)]})
    assert list(converted) == [key, (1, 2)]
    assert converted[key] == {"x_value": 1, "label": None, "tags": []}
    assert converted[(1, 2)] == [{"x_value": 2, "label": None, "tags": []}]


def test_logging_sees_the_converted_body(transport, caplog):
    transport.add(httpx.Response(204))
    client = ApiClient(HOST, transport=transport, verbose=True)
    with caplog.at_level(logging.INFO, logger="dazapiz.http"):
        client.fetch("/things", "POST", json=Thing(thing_id=1, display_name="a"))
    messages = [r.getMessage() for r in caplog.records]
    assert messages[1:3] == [f"{INFO} >>> body:", '{\n  "thingId": 1,\n  "displayName": "a"\n}']
