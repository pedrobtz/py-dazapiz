"""Fixtures for testing `AzurePetStoreClient` offline: copy this file for your client.

Nothing here reaches Azure or the network. `respx` answers the client's
HTTP requests, `StaticTokenCredential` stands in for its Entra ID
credential, and `pytest-socket` makes any other connection attempt (an
unmocked HTTP client, MSAL, azure-identity, a DNS lookup) fail the test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import respx
from azure_petstore import AzurePetStoreClient
from petstore import PETSTORE_URL
from pytest_socket import disable_socket, enable_socket

from dazure.testing import StaticTokenCredential


@pytest.fixture(autouse=True)
def no_network() -> Iterator[None]:
    """Block every socket but Unix ones, for each test in this directory."""
    disable_socket(allow_unix_socket=True)
    yield
    enable_socket()


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    """The fake API: add routes with `api.get("/pet/7").respond(...)`.

    An unmatched request raises instead of going out (`assert_all_mocked`,
    respx's default); routes a test adds but does not call are allowed.
    """
    with respx.mock(base_url=PETSTORE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def credential() -> StaticTokenCredential:
    """A credential that hands out "fake-token" and records the scopes asked for."""
    return StaticTokenCredential()


@pytest.fixture
def store(
    api: respx.MockRouter, credential: StaticTokenCredential
) -> Iterator[AzurePetStoreClient]:
    """The client under test, on the fake API and the fake credential."""
    with AzurePetStoreClient(credential=credential) as client:
        yield client
