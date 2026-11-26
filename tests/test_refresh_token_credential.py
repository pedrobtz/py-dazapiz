"""RefreshTokenCredential with msal's PublicClientApplication patched (design §4.3.5).

`PublicClientApplication.__init__` runs instance and tenant discovery over the
network, so the fake replaces the class, recording what it was built with and
what `acquire_token_by_refresh_token` was handed.
"""

import pytest
from azure.core.credentials import AccessToken, TokenCredential
from azure.core.exceptions import ClientAuthenticationError

import dazapiz._credential
from dazapiz import (
    AZURE_CLI_CLIENT_ID,
    RefreshTokenCredential,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SupportsRefreshToken,
)

SCOPE = "https://storage.azure.com/.default"
INFO = RefreshTokenInfo("rt-0", "cid", "tid", "a@x")


class FakeApp:
    """Stands in for msal.PublicClientApplication; `responses` are served in order."""

    built: list
    calls: list
    responses: list

    def __init__(self, client_id, authority=None, **kwargs):
        type(self).built.append({"client_id": client_id, "authority": authority, **kwargs})

    def acquire_token_by_refresh_token(self, refresh_token, scopes, **kwargs):
        type(self).calls.append({"refresh_token": refresh_token, "scopes": scopes, **kwargs})
        return type(self).responses.pop(0)


def ok(n, *, expires_in=3600, refresh_token=None):
    response = {"access_token": f"at-{n}", "token_type": "Bearer", "expires_in": expires_in}
    if refresh_token:
        response["refresh_token"] = refresh_token
    return response


@pytest.fixture
def app(monkeypatch):
    FakeApp.built, FakeApp.calls, FakeApp.responses = [], [], []
    monkeypatch.setattr(dazapiz._credential.msal, "PublicClientApplication", FakeApp)
    for name in (
        "AZURE_AUTHORITY_HOST",
        "AZURE_REFRESH_TOKEN",
        "AZURE_CLIENT_ID",
        "AZURE_TENANT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    return FakeApp


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(dazapiz._credential.time, "time", lambda: now["t"])
    return now


def test_implements_both_protocols(app):
    cred = RefreshTokenCredential(INFO)
    assert isinstance(cred, TokenCredential)
    assert isinstance(cred, SupportsRefreshToken)
    assert app.built == []  # msal is not touched before the first get_token()


def test_hands_msal_the_token_scopes_client_and_authority(app, clock):
    app.responses = [ok(1)]
    token = RefreshTokenCredential(INFO).get_token(SCOPE, "other/.default")
    assert token == AccessToken("at-1", int(clock["t"]) + 3600)
    assert app.built == [{"client_id": "cid", "authority": "https://login.microsoftonline.com/tid"}]
    assert app.calls == [{"refresh_token": "rt-0", "scopes": [SCOPE, "other/.default"]}]


def test_authority_host(app, monkeypatch):
    app.responses = [ok(1), ok(2), ok(3)]
    RefreshTokenCredential(INFO, authority_host="login.microsoftonline.us").get_token(SCOPE)
    RefreshTokenCredential(INFO, authority_host="https://login.chinacloudapi.cn/").get_token(SCOPE)
    monkeypatch.setenv("AZURE_AUTHORITY_HOST", "https://login.microsoftonline.us")
    RefreshTokenCredential(INFO).get_token(SCOPE)
    assert [b["authority"] for b in app.built] == [
        "https://login.microsoftonline.us/tid",
        "https://login.chinacloudapi.cn/tid",
        "https://login.microsoftonline.us/tid",
    ]


def test_string_takes_the_4_3_4_defaults(app, monkeypatch):
    app.responses = [ok(1), ok(2)]
    RefreshTokenCredential("rt-s").get_token(SCOPE)
    monkeypatch.setenv("AZURE_REFRESH_TOKEN", "rt-env")
    monkeypatch.setenv("AZURE_TENANT_ID", "env-tid")
    RefreshTokenCredential().get_token(SCOPE)
    assert [(b["client_id"], b["authority"]) for b in app.built] == [
        (AZURE_CLI_CLIENT_ID, "https://login.microsoftonline.com/common"),
        (AZURE_CLI_CLIENT_ID, "https://login.microsoftonline.com/env-tid"),
    ]
    assert [c["refresh_token"] for c in app.calls] == ["rt-s", "rt-env"]


def test_no_token_anywhere(app):
    with pytest.raises(RefreshTokenNotFoundError):
        RefreshTokenCredential()


@pytest.mark.parametrize(
    ("elapsed", "calls"),
    [
        (3600 - 301, 1),  # 301 s left: cached
        (3600 - 300, 2),  # 300 s left: five minutes, renewed
        (3600 - 299, 2),
    ],
)
def test_cached_until_five_minutes_before_expiry(app, clock, elapsed, calls):
    app.responses = [ok(1), ok(2)]
    cred = RefreshTokenCredential(INFO)
    assert cred.get_token(SCOPE).token == "at-1"
    clock["t"] += elapsed
    assert cred.get_token(SCOPE).token == f"at-{calls}"
    assert len(app.calls) == calls


def test_cache_is_per_scope_set_and_tenant(app, clock):
    app.responses = [ok(1), ok(2), ok(3)]
    cred = RefreshTokenCredential(INFO)
    cred.get_token(SCOPE)
    cred.get_token("other/.default")
    cred.get_token(SCOPE, tenant_id="tid-2")
    assert cred.get_token(SCOPE).token == "at-1"
    assert len(app.calls) == 3
    assert [b["authority"] for b in app.built] == [
        "https://login.microsoftonline.com/tid",
        "https://login.microsoftonline.com/tid-2",
    ]


def test_rotated_refresh_token_is_kept(app, clock):
    app.responses = [ok(1, refresh_token="rt-1"), ok(2)]
    cred = RefreshTokenCredential(INFO)
    cred.get_token(SCOPE)
    assert cred.get_refresh_token() == RefreshTokenInfo("rt-1", "cid", "tid", "a@x")
    cred.get_token("other/.default")
    assert [c["refresh_token"] for c in app.calls] == ["rt-0", "rt-1"]
    # No new refresh token in the response: the last one stays.
    assert cred.get_refresh_token().token == "rt-1"


def test_get_refresh_token_before_any_call(app):
    assert RefreshTokenCredential(INFO).get_refresh_token() == INFO


def test_claims_go_to_msal_and_skip_the_cache(app, clock):
    app.responses = [ok(1), ok(2)]
    cred = RefreshTokenCredential(INFO)
    cred.get_token(SCOPE)
    assert cred.get_token(SCOPE, claims='{"access_token":{}}').token == "at-2"
    assert app.calls[1]["data"] == {"claims": '{"access_token":{}}'}


def test_msal_error_becomes_client_authentication_error(app):
    app.responses = [
        {"error": "invalid_grant", "error_description": "AADSTS70000: the grant is expired."}
    ]
    with pytest.raises(ClientAuthenticationError, match="invalid_grant") as err:
        RefreshTokenCredential(INFO).get_token(SCOPE)
    assert "AADSTS70000" in str(err.value)


def test_needs_a_scope(app):
    with pytest.raises(ValueError, match="scope"):
        RefreshTokenCredential(INFO).get_token()
    assert app.calls == []
