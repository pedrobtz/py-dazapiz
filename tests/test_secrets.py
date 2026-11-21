"""A sentinel secret never appears in repr, str or an error message (design §6)."""

import pytest
from azure.core.exceptions import ClientAuthenticationError
from helpers import Login, subscription, write_az_login, write_profile, write_token_cache

import dazure._az_cli_token
import dazure._credential
from dazure import (
    RefreshTokenCredential,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    refresh_token_from_az_cli,
)
from dazure._refresh_token import as_refresh_token_info

SENTINEL = "SENTINEL-7f3c9a-refresh-token"
TENANT = "11111111-1111-1111-1111-111111111111"


def shown(obj) -> str:
    return repr(obj) + str(obj) + f"{obj}" + f"{obj!r}"


def test_refresh_token_info():
    info = RefreshTokenInfo(SENTINEL, "cid", "tid", "a@x")
    assert SENTINEL not in shown(info)
    assert "cid" in repr(info)
    assert SENTINEL not in shown([info, {"k": info}])


def test_coerced_string(monkeypatch):
    monkeypatch.setenv("AZURE_REFRESH_TOKEN", SENTINEL)
    assert SENTINEL not in shown(as_refresh_token_info(None))
    assert SENTINEL not in shown(as_refresh_token_info(SENTINEL))


class FakeApp:
    response: dict

    def __init__(self, client_id, authority=None, **kwargs):
        pass

    def acquire_token_by_refresh_token(self, refresh_token, scopes, **kwargs):
        return type(self).response


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(dazure._credential.msal, "PublicClientApplication", FakeApp)
    return FakeApp


def test_credential_repr_including_after_rotation(app):
    cred = RefreshTokenCredential(SENTINEL)
    assert SENTINEL not in shown(cred)
    app.response = {"access_token": "at", "expires_in": 3600, "refresh_token": SENTINEL + "-2"}
    cred.get_token("s/.default")
    assert SENTINEL not in shown(cred)
    assert SENTINEL not in shown(cred.get_refresh_token())


def test_msal_error_echoing_the_token(app):
    # Even if the authority echoed the token back, the message drops it.
    app.response = {"error": "invalid_grant", "error_description": f"bad token {SENTINEL}"}
    with pytest.raises(ClientAuthenticationError) as err:
        RefreshTokenCredential(SENTINEL).get_token("s/.default")
    assert SENTINEL not in shown(err.value)
    assert SENTINEL not in str(err.value.message)
    assert "invalid_grant" in str(err.value)


def test_az_cli_lookup_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(dazure._az_cli_token, "_is_windows", lambda: False)
    other = Login("bob@fabrikam.com", TENANT, TENANT, SENTINEL)
    write_token_cache(tmp_path, [other])
    write_profile(tmp_path, [subscription("alice@contoso.com", TENANT, is_default=True)])
    with pytest.raises(RefreshTokenNotFoundError) as err:
        refresh_token_from_az_cli(config_dir=tmp_path)
    assert SENTINEL not in shown(err.value)

    write_az_login(tmp_path, [other], default=other)
    info = refresh_token_from_az_cli(config_dir=tmp_path)
    assert info.token == SENTINEL
    assert SENTINEL not in shown(info)
