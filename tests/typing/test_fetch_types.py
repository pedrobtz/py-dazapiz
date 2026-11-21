"""The static types of `ApiClient.fetch()` (design §4.1, §8.1).

pyright checks this file in strict mode (`[tool.pyright]`): each
`assert_type` is a type assertion that fails the lint job if `fetch()`'s
overloads infer anything else. pytest runs it too, against a mock
transport, so the values behind the types are what they claim.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, TypeAdapter
from typing_extensions import assert_type

from dazure import ApiClient

HOST = "https://api.example.com"


class Item(BaseModel):
    id: int


class ItemClient(ApiClient):
    host_url = HOST

    def item(self, item_id: int) -> Item:
        return self.fetch("/items/{item_id}", item_id=str(item_id), parse=Item.model_validate)


def _reply(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/items":
        return httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    if request.url.path == "/xml":
        return httpx.Response(200, content=b"<a/>", headers={"content-type": "application/xml"})
    return httpx.Response(200, json={"id": 7})


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> ApiClient:
    monkeypatch.setattr("dazure._api_client._transport", lambda: httpx.MockTransport(_reply))
    return ApiClient(HOST)


def test_without_parse_fetch_is_any(client: ApiClient) -> None:
    result = assert_type(client.fetch("/items/{n}", n="7"), Any)
    assert result == {"id": 7}


def test_parse_types_the_result(client: ApiClient) -> None:
    item = assert_type(client.fetch("/items/7", parse=Item.model_validate), Item)
    assert item == Item(id=7)

    items = assert_type(
        client.fetch("/items", parse=TypeAdapter(list[Item]).validate_python), list[Item]
    )
    assert items == [Item(id=1), Item(id=2)]

    def root_tag(content: Any) -> str:
        assert type(content) is ET.Element
        return str(content.tag)

    tag = assert_type(client.fetch("/xml", parse=root_tag), str)
    assert tag == "a"

    count = assert_type(client.fetch("/items", parse=len), int)
    assert count == 2


def test_parse_types_in_a_subclass_and_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dazure._api_client._transport", lambda: httpx.MockTransport(_reply))
    with ItemClient() as api:
        assert_type(api, ItemClient)
        assert assert_type(api.item(7), Item) == Item(id=7)
