"""A sentinel secret never appears in repr, str or an error message (design §6)."""

import pprint

import pytest
from azure.core.exceptions import ClientAuthenticationError
from helpers import Login, subscription, write_az_login, write_profile, write_token_cache

import dazure._az_cli_token
import dazure._credential
from dazure import (
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    RefreshTokenCredential,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SparkStorageConf,
    refresh_token_from_az_cli,
    spark_storage_conf,
)
from dazure._interactive import find_refresh_token
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


@pytest.mark.parametrize("prefix", ["spark.hadoop", None])
@pytest.mark.parametrize("storage_account", [None, "acct", "endpoint", "key"])
def test_spark_storage_conf(prefix, storage_account):
    # "endpoint" and "key" as account names put a secret key's property in
    # front of a word that is also a property: the refresh token key for the
    # account "endpoint" reads `...oauth2.refresh.token.endpoint.dfs...`.
    secret, key = SENTINEL + "-secret", SENTINEL + "-key"
    confs = [
        spark_storage_conf(refresh_token=SENTINEL, storage_account=storage_account, prefix=prefix),
        spark_storage_conf(
            refresh_token=RefreshTokenInfo(SENTINEL, "cid", "tid"),
            storage_account=storage_account,
            prefix=prefix,
        ),
        spark_storage_conf(
            "client_secret",
            client_id="cid",
            tenant_id="tid",
            client_secret=secret,
            storage_account=storage_account,
            prefix=prefix,
        ),
    ]
    if storage_account is not None:
        confs.append(
            spark_storage_conf(
                "shared_key", storage_account=storage_account, account_key=key, prefix=prefix
            )
        )
    for conf in confs:
        assert SENTINEL not in shown(conf)
        assert SENTINEL not in pprint.pformat(conf)
        assert SENTINEL not in shown(conf.copy())
        assert SENTINEL not in shown(conf | {"x": "y"})
        assert SENTINEL not in shown({"conf": conf})
        assert "<redacted>" in repr(conf)
        assert any(SENTINEL in v for v in conf.values())  # the dict keeps the real value
    rt, cs = confs[0], confs[2]
    # The non-secret values still show.
    endpoint = next(v for v in rt.values() if v.startswith("https://"))
    assert endpoint in repr(rt)
    assert "cid" in repr(cs)


def test_spark_storage_conf_built_by_hand():
    conf = SparkStorageConf(
        {
            "fs.azure.account.key.a.dfs.core.windows.net": SENTINEL,
            "fs.azure.account.oauth2.client.secret": SENTINEL,
            "spark.hadoop.fs.azure.account.oauth2.refresh.token.b.dfs.core.windows.net": SENTINEL,
            "fs.azure.account.auth.type": "OAuth",
        }
    )
    assert SENTINEL not in shown(conf)
    assert "OAuth" in repr(conf)


def test_interactive_cache_lookup(tmp_path, monkeypatch):
    # The lookup's result and its not-found error, with other accounts' tokens in the cache.
    import azure.identity._persistent_cache as persistent_cache
    from test_interactive import OPTIONS, Store, record_of

    store = Store(tmp_path)
    monkeypatch.setattr(persistent_cache, "_get_persistence", store.get_persistence)
    alice = Login("alice@contoso.com", TENANT, TENANT, SENTINEL)
    bob = Login("bob@contoso.com", TENANT, TENANT, SENTINEL + "-bob")
    store.write("dazure.nocae", [bob])
    with pytest.raises(RefreshTokenNotFoundError) as err:
        find_refresh_token(OPTIONS, record_of(alice))
    assert SENTINEL not in shown(err.value)

    store.write("dazure.nocae", [alice, bob])
    cred = DeviceCodeCredential(authentication_record=record_of(alice))
    info = cred.get_refresh_token()
    assert info.token == SENTINEL
    assert SENTINEL not in shown(info)
    assert SENTINEL not in shown(cred)


def test_pasted_code_errors(monkeypatch):
    # The authorization code the user pasted is not echoed by any refusal.
    from test_pasted_code import REDIRECT, FakeApp

    import dazure._session

    cred = InteractiveBrowserCredential(redirect_uri=REDIRECT)
    app = FakeApp(error=ValueError("state mismatch: STATE-from-msal vs other"))
    monkeypatch.setattr(cred, "_get_app", lambda **kw: app)
    monkeypatch.setattr(dazure._session, "is_interactive", lambda: True)
    for reply in (f"{REDIRECT}?code={SENTINEL}&state=other", f"{REDIRECT}?code={SENTINEL}"):
        monkeypatch.setattr("builtins.input", lambda prompt="", reply=reply: reply)
        with pytest.raises(ClientAuthenticationError) as err:
            cred._request_token("User.Read")
        assert SENTINEL not in shown(err.value)
