"""`dazapiz.testing.StaticTokenCredential`: a fake `TokenCredential` for tests."""

from __future__ import annotations

import time

import httpx
from azure.core.credentials import AccessToken, AccessTokenInfo, SupportsTokenInfo, TokenCredential

import dazapiz
import dazapiz.testing
from dazapiz import ApiClient
from dazapiz.testing import StaticTokenCredential


def test_get_token_returns_the_token_with_an_expiry():
    before = int(time.time())
    token = StaticTokenCredential("tok", expires_in=600).get_token("api://x/.default")
    assert isinstance(token, AccessToken)
    assert token.token == "tok"
    assert before + 600 <= token.expires_on <= int(time.time()) + 600


def test_default_token():
    assert StaticTokenCredential().get_token("s").token == "fake-token"


def test_calls_record_scopes_claims_and_tenant():
    cred = StaticTokenCredential()
    cred.get_token("a/.default", "b/.default")
    cred.get_token("c/.default", claims="{}", tenant_id="t1")
    cred.get_token_info("d/.default", options={"tenant_id": "t2"})
    assert cred.calls == [("a/.default", "b/.default"), ("c/.default",), ("d/.default",)]


def test_get_token_info():
    info = StaticTokenCredential("tok", expires_in=60).get_token_info("s")
    assert isinstance(info, AccessTokenInfo)
    assert info.token == "tok"
    assert info.token_type == "Bearer"
    assert info.expires_on >= int(time.time()) + 59


def test_is_a_token_credential():
    cred = StaticTokenCredential()
    assert isinstance(cred, TokenCredential)
    assert isinstance(cred, SupportsTokenInfo)


def test_context_manager_and_close():
    with StaticTokenCredential() as cred:
        cred.close()


def test_api_client_sends_it_as_bearer():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    class Client(ApiClient):
        host_url = "https://api.example.com"
        scope = "api://app/.default"

    cred = StaticTokenCredential("tok-1")
    client = Client(credential=cred, transport=httpx.MockTransport(handler))
    assert client.fetch("/x") == {"ok": True}
    assert seen[0].headers["Authorization"] == "Bearer tok-1"
    assert cred.calls == [("api://app/.default",)]


def test_only_exported_from_dazapiz_testing():
    assert not hasattr(dazapiz, "StaticTokenCredential")
    assert "StaticTokenCredential" not in dazapiz.__all__
    assert dazapiz.testing.__all__ == ["StaticTokenCredential"]
