"""`AzurePetStoreClient` tested in CI: no Azure, no network.

The fixtures (`api`, `credential`, `store`) are in `conftest.py`. Each test
scripts the API's answer with respx, calls the client, and checks what it
returned and what it sent.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from azure.identity import AzureCliCredential, ChainedTokenCredential, ClientSecretCredential
from azure_petstore import AzurePetStoreClient
from petstore import Pet, PetCreate, PetNotFoundError
from pydantic import HttpUrl
from pytest_socket import SocketBlockedError

from dazure import ApiError, ResponseParseError
from dazure.testing import StaticTokenCredential

PET = {"id": 7, "name": "Rex", "photoUrls": ["https://example.com/rex.png"], "status": "available"}


def test_get_pet_returns_a_validated_pet_and_sends_the_token(
    api: respx.MockRouter, store: AzurePetStoreClient, credential: StaticTokenCredential
) -> None:
    route = api.get("/pet/7").respond(json=PET)

    pet = store.get_pet(7)

    assert pet == Pet(
        id=7, name="Rex", photo_urls=["https://example.com/rex.png"], status="available"
    )
    assert route.call_count == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer fake-token"
    assert credential.calls == [("api://00000000-0000-0000-0000-000000000000/.default",)]


def test_add_pet_sends_the_model_as_json(api: respx.MockRouter, store: AzurePetStoreClient) -> None:
    route = api.post("/pet").respond(json=PET)

    store.add_pet(PetCreate(id=7, name="Rex", photo_urls=[HttpUrl("https://example.com/rex.png")]))

    # camelCase, and only the fields that were set: no "status": null.
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"id": 7, "name": "Rex", "photoUrls": ["https://example.com/rex.png"]}


def test_a_malformed_pet_is_a_parse_error(
    api: respx.MockRouter, store: AzurePetStoreClient
) -> None:
    api.get("/pet/7").respond(json={"id": 7, "photoUrls": []})  # no "name"

    with pytest.raises(ResponseParseError):
        store.get_pet(7)


def test_404_is_pet_not_found(api: respx.MockRouter, store: AzurePetStoreClient) -> None:
    api.get("/pet/7").respond(404, json={"message": "Pet not found"})

    with pytest.raises(PetNotFoundError) as err:
        store.get_pet(7)

    assert isinstance(err.value.__cause__, ApiError)
    assert err.value.__cause__.response.status_code == 404


def test_503_is_retried(api: respx.MockRouter, credential: StaticTokenCredential) -> None:
    waits: list[float] = []
    route = api.get("/pet/7")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=PET)]

    # sleep= receives each retry wait instead of time.sleep: no real waiting.
    with AzurePetStoreClient(credential=credential, sleep=waits.append) as store:
        assert store.get_pet(7).id == 7
    assert route.call_count == 2
    assert len(waits) == 1


def test_500_is_not_retried(api: respx.MockRouter, credential: StaticTokenCredential) -> None:
    waits: list[float] = []
    route = api.get("/pet/7").respond(500)

    with (
        AzurePetStoreClient(credential=credential, sleep=waits.append) as store,
        pytest.raises(ApiError),
    ):
        store.get_pet(7)
    assert route.call_count == 1
    assert waits == []


# Which credential the client picks, by environment, without fetching a token ----


def test_service_principal_when_its_variables_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_TOKEN_CREDENTIALS", raising=False)
    monkeypatch.setenv("PETSTORE_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("PETSTORE_CLIENT_SECRET", "not-a-secret")
    monkeypatch.setenv("AZURE_TENANT_ID", "00000000-0000-0000-0000-000000000002")

    with AzurePetStoreClient() as client:
        assert isinstance(client.credential, ClientSecretCredential)


def test_your_az_login_when_they_are_not(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_TOKEN_CREDENTIALS", "PETSTORE_CLIENT_ID", "PETSTORE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)

    with AzurePetStoreClient() as client:
        credential = client.credential
    assert isinstance(credential, ChainedTokenCredential)
    # Then the device code, but only in an interactive session.
    assert isinstance(credential.credentials[0], AzureCliCredential)


# The guards: nothing leaves the machine -------------------------------------------


def test_an_unmocked_request_fails(api: respx.MockRouter, store: AzurePetStoreClient) -> None:
    with pytest.raises(AssertionError, match="not mocked"):
        store.get_pet(8)  # no route for /pet/8


def test_any_other_connection_is_blocked() -> None:
    with (
        pytest.raises(SocketBlockedError),
        pytest.warns(UserWarning, match="tried to use socket"),
    ):
        httpx.get("https://petstore3.swagger.io/api/v3/pet/7")
