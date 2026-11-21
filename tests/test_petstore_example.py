"""`examples/petstore.py` against Petstore-shaped responses and its OpenAPI document.

The requests are checked as the recording transport received them; the
models against `tests/fixtures/petstore-openapi.json` (design §8.1, D53).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

import httpx

# examples/ is on pytest's `pythonpath`, so the example imports by name, as
# examples/tests/ imports it: one module object, one set of model classes.
import petstore as ps
import pytest
from pydantic import BaseModel, HttpUrl, ValidationError
from recording_transport import RecordingTransport, json_response

import dazure._api_client
from dazure import ApiError, ResponseParseError

ROOT = Path(__file__).parent.parent
BASE = "https://petstore3.swagger.io/api/v3"


SPEC = json.loads((ROOT / "tests" / "fixtures" / "petstore-openapi.json").read_text("utf-8"))
SCHEMAS = SPEC["components"]["schemas"]

PET = {
    "id": 10,
    "name": "doggie",
    "category": {"id": 1, "name": "Dogs"},
    "photoUrls": ["https://example.com/d.png"],
    "tags": [{"id": 2, "name": "good"}],
    "status": "available",
}
ORDER = {
    "id": 5,
    "petId": 10,
    "quantity": 2,
    "shipDate": "2026-11-21T10:00:00.000+00:00",
    "status": "placed",
    "complete": False,
}


@pytest.fixture
def transport(monkeypatch) -> RecordingTransport:
    t = RecordingTransport()
    monkeypatch.setattr(dazure._api_client, "_transport", lambda: t)
    return t


@pytest.fixture
def store(transport):
    with ps.PetStoreClient() as client:
        yield client


def sent(transport, i=-1):
    """(method, path?query, JSON body or None) of a recorded request."""
    r = transport.requests[i]
    target = r.url.raw_path.decode()
    return r.method, target, json.loads(r.body) if r.body else None


# Requests and responses ------------------------------------------------------------


def test_add_pet_sends_only_what_was_set(store, transport):
    transport.add(json_response(200, PET))
    pet = store.add_pet(
        ps.PetCreate(id=10, name="doggie", photo_urls=[HttpUrl("https://example.com/d.png")])
    )
    assert sent(transport) == (
        "POST",
        "/api/v3/pet",
        {"id": 10, "name": "doggie", "photoUrls": ["https://example.com/d.png"]},
    )
    r = transport.requests[0]
    assert r.headers["accept"] == "application/json"
    assert r.headers["content-type"] == "application/json"
    assert "authorization" not in r.headers  # the store is open: no credential
    assert pet == ps.Pet.model_validate(PET)
    assert pet.category == ps.Category(id=1, name="Dogs")
    assert pet.tags == [ps.Tag(id=2, name="good")]


def test_add_pet_with_every_field(store, transport):
    transport.add(json_response(200, PET))
    store.add_pet(
        ps.PetCreate(
            id=10,
            name="doggie",
            photo_urls=["https://example.com/d.png"],
            category=ps.Category(id=1, name="Dogs"),
            tags=[ps.Tag(id=2, name="good")],
            status="available",
        )
    )
    assert sent(transport)[2] == PET


def test_get_pet(store, transport):
    transport.add(json_response(200, PET))
    pet = store.get_pet(10)
    assert sent(transport) == ("GET", "/api/v3/pet/10", None)
    assert pet.id == 10 and pet.photo_urls == ["https://example.com/d.png"]


def test_find_pets_by_status_sends_one_request_per_status(store, transport):
    sold = {**PET, "id": 11, "status": "sold"}
    transport.add(json_response(200, [PET]), json_response(200, [sold]))
    pets = store.find_pets_by_status(["available", "sold", "available"])
    assert [sent(transport, i)[:2] for i in range(2)] == [
        ("GET", "/api/v3/pet/findByStatus?status=available"),
        ("GET", "/api/v3/pet/findByStatus?status=sold"),
    ]
    assert [p.id for p in pets] == [10, 11]
    assert all(isinstance(p, ps.Pet) for p in pets)


def test_find_pets_by_status_with_no_pets(store, transport):
    transport.add(json_response(200, []))
    assert store.find_pets_by_status(("pending",)) == []


@pytest.mark.parametrize(
    ("status", "error"),
    [("sold", TypeError), ([], ValueError), (["available", "lost"], ValidationError)],
    ids=["a-string", "empty", "unknown"],
)
def test_find_pets_by_status_refusals_send_nothing(store, transport, status, error):
    with pytest.raises(error):
        store.find_pets_by_status(status)
    assert transport.requests == []


def test_update_pet_sends_the_whole_pet(store, transport):
    transport.add(json_response(200, PET), json_response(200, {**PET, "status": "sold"}))
    pet = store.get_pet(10)
    updated = store.update_pet(pet.model_copy(update={"status": "sold"}))
    assert sent(transport) == ("PUT", "/api/v3/pet", {**PET, "status": "sold"})
    assert updated.status == "sold"


def test_delete_pet(store, transport):
    # The store labels its plain-text reply as JSON.
    transport.add(
        httpx.Response(200, content=b"Pet deleted", headers={"content-type": "application/json"})
    )
    assert store.delete_pet(10) is None
    assert sent(transport) == ("DELETE", "/api/v3/pet/10", None)


def test_place_order(store, transport):
    transport.add(json_response(200, ORDER))
    order = store.place_order(
        ps.OrderCreate(
            pet_id=10, quantity=2, ship_date=datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        )
    )
    assert sent(transport) == (
        "POST",
        "/api/v3/store/order",
        {"petId": 10, "quantity": 2, "shipDate": "2026-11-21T10:00:00Z"},
    )
    assert order.id == 5
    assert order.ship_date == datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
    assert order.status == "placed" and order.complete is False


def test_get_and_delete_order(store, transport):
    transport.add(json_response(200, ORDER), httpx.Response(200))
    assert store.get_order(5) == ps.Order.model_validate(ORDER)
    store.delete_order(5)
    assert [sent(transport, i)[:2] for i in range(2)] == [
        ("GET", "/api/v3/store/order/5"),
        ("DELETE", "/api/v3/store/order/5"),
    ]


# Response validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {k: v for k, v in PET.items() if k != "name"},
        {k: v for k, v in PET.items() if k != "id"},
        {k: v for k, v in PET.items() if k != "photoUrls"},
        {**PET, "status": "lost"},
        {**PET, "id": -1},
        {**PET, "tags": "good"},
        "not a pet",
    ],
    ids=["no-name", "no-id", "no-photoUrls", "unknown-status", "negative-id", "tags", "a-string"],
)
def test_malformed_pet_response_is_a_parse_error(store, transport, body):
    transport.add(json_response(200, body))
    with pytest.raises(ResponseParseError) as err:
        store.get_pet(10)
    assert isinstance(err.value.__cause__, ValidationError)
    assert str(err.value).startswith(f"GET {BASE}/pet/10: ")


def test_one_malformed_pet_fails_find(store, transport):
    transport.add(json_response(200, [PET, {**PET, "status": "lost"}]))
    with pytest.raises(ResponseParseError) as err:
        store.find_pets_by_status(["available"])
    assert isinstance(err.value.__cause__, ValidationError)


def test_unknown_order_status_is_a_parse_error(store, transport):
    transport.add(json_response(200, {**ORDER, "status": "lost"}))
    with pytest.raises(ResponseParseError):
        store.get_order(5)


def test_response_photo_url_is_a_string_as_the_schema_says(store, transport):
    # D53: the schema types photoUrls as plain strings, and the public store
    # holds pets whose photo URL is "string"; responses are not held to more.
    transport.add(json_response(200, {**PET, "photoUrls": ["string"]}))
    assert store.get_pet(10).photo_urls == ["string"]


def test_unknown_response_fields_are_ignored(store, transport):
    transport.add(json_response(200, {**PET, "owner": "someone", "category": {"x": 1}}))
    pet = store.get_pet(10)
    assert pet.model_extra is None  # extra="ignore": not kept
    assert not hasattr(pet, "owner")
    assert pet.category == ps.Category()


# Request validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"photo_urls": ["https://example.com/d.png"]},
        {"name": "", "photo_urls": []},
        {"name": "d", "photo_urls": ["not a url"]},
        {"name": "d", "photo_urls": [], "status": "lost"},
        {"name": "d", "photo_urls": [], "id": -1},
        {"name": "d", "photo_urls": [], "id": 2**63},
        {"name": "d", "photo_urls": [], "colour": "brown"},
        {"name": "d", "photoUrls": [], "photo_urls": [], "nmae": "x"},
    ],
    ids=[
        "no-name",
        "empty-name",
        "bad-url",
        "status",
        "negative-id",
        "id-past-int64",
        "extra",
        "typo",
    ],
)
def test_invalid_pet_create_fails_before_sending(store, transport, kwargs):
    with pytest.raises(ValidationError):
        store.add_pet(ps.PetCreate(**kwargs))
    assert transport.requests == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": 1},
        {"pet_id": 1},
        {"pet_id": 1, "quantity": 0},
        {"pet_id": 1, "quantity": 1, "status": "x"},
    ],
    ids=["no-pet", "no-quantity", "zero-quantity", "status"],
)
def test_invalid_order_create_fails_before_sending(store, transport, kwargs):
    with pytest.raises(ValidationError):
        store.place_order(ps.OrderCreate(**kwargs))
    assert transport.requests == []


def test_models_are_frozen_and_take_names_or_aliases():
    by_name = ps.PetCreate(name="d", photo_urls=[])
    by_alias = ps.PetCreate.model_validate({"name": "d", "photoUrls": []})
    assert by_name == by_alias
    with pytest.raises(ValidationError):
        by_name.name = "e"  # type: ignore[misc]
    assert ps.Order.model_validate({"id": 1, "pet_id": 2}).pet_id == 2


# Domain errors -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call", "error"),
    [("get_pet", ps.PetNotFoundError), ("get_order", ps.OrderNotFoundError)],
)
def test_404_is_a_domain_error_chained_to_api_error(store, transport, call, error):
    transport.add(
        httpx.Response(404, text="Not found", headers={"content-type": "application/xml"})
    )
    with pytest.raises(error, match=r"No (pet|order) with id 99") as err:
        getattr(store, call)(99)
    cause = err.value.__cause__
    assert isinstance(cause, ApiError)
    assert cause.response.status_code == 404


@pytest.mark.parametrize("call", ["get_pet", "get_order"])
def test_other_errors_stay_api_errors(store, transport, call):
    transport.add(httpx.Response(400, text="Invalid ID supplied"))
    with pytest.raises(ApiError) as err:
        getattr(store, call)(99)
    assert not isinstance(err.value, LookupError)


# Spec oracle: the models against the OpenAPI document --------------------------------

# Deliberate differences from the schema's `required` (D53): the store always
# returns an id, and an order needs a pet and a quantity.
EXTRA_REQUIRED = {
    "PetCreate": set(),
    "Pet": {"id"},
    "OrderCreate": {"petId", "quantity"},
    "Order": {"id"},
    "Category": set(),
    "Tag": set(),
}
SCHEMA_OF = {
    "PetCreate": "Pet",
    "Pet": "Pet",
    "OrderCreate": "Order",
    "Order": "Order",
    "Category": "Category",
    "Tag": "Tag",
}
MINIMAL = {
    "PetCreate": {"name": "d", "photoUrls": []},
    "Pet": {"id": 1, "name": "d", "photoUrls": []},
    "OrderCreate": {"petId": 1, "quantity": 1},
    "Order": {"id": 1},
    "Category": {},
    "Tag": {},
}


def _model(name: str) -> type[BaseModel]:
    return getattr(ps, name)


def _aliases(model: type[BaseModel], required_only: bool = False) -> set[str]:
    return {
        f.alias or name
        for name, f in model.model_fields.items()
        if f.is_required() or not required_only
    }


def test_spec_fixture_is_the_recorded_version():
    assert SPEC["info"]["version"] == "1.0.27"
    assert SPEC["info"]["license"]["name"] == "Apache 2.0"


@pytest.mark.parametrize("name", list(SCHEMA_OF))
def test_property_names_are_the_aliases(name):
    assert _aliases(_model(name)) == set(SCHEMAS[SCHEMA_OF[name]]["properties"])


@pytest.mark.parametrize("name", list(SCHEMA_OF))
def test_required_fields_match_the_schema(name):
    schema_required = set(SCHEMAS[SCHEMA_OF[name]].get("required", []))
    assert _aliases(_model(name), required_only=True) == schema_required | EXTRA_REQUIRED[name]


def test_status_enums_match_the_schema():
    pet_enum = SCHEMAS["Pet"]["properties"]["status"]["enum"]
    assert list(get_args(ps.PetStatus)) == pet_enum
    assert list(get_args(ps.OrderStatus)) == SCHEMAS["Order"]["properties"]["status"]["enum"]
    (param,) = SPEC["paths"]["/pet/findByStatus"]["get"]["parameters"]
    assert param["schema"]["enum"] == pet_enum


def _examples():
    for name, schema in SCHEMA_OF.items():
        for prop, spec in SCHEMAS[schema]["properties"].items():
            if "example" in spec:
                yield pytest.param(name, prop, spec["example"], id=f"{name}.{prop}")


EXAMPLES = list(_examples())


def test_the_schema_has_examples():
    assert len(EXAMPLES) >= 10


@pytest.mark.parametrize(("name", "prop", "example"), EXAMPLES)
def test_schema_examples_validate(name, prop, example):
    model = _model(name).model_validate({**MINIMAL[name], prop: example})
    assert model.model_dump(mode="json", by_alias=True)[prop] == example


@pytest.mark.parametrize("name", list(SCHEMA_OF))
def test_minimal_bodies_validate(name):
    # The base each example is put in is valid on its own.
    _model(name).model_validate(MINIMAL[name])
