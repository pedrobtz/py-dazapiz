"""A sentinel secret never appears in repr, str or an error message (design §6)."""

import pprint

import pytest
from azure.core.exceptions import ClientAuthenticationError
from helpers import Login, subscription, write_az_login, write_profile, write_token_cache

import dazapiz._az_cli_token
import dazapiz._credential
from dazapiz import (
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    RefreshTokenCredential,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SparkStorageConf,
    refresh_token_from_az_cli,
    spark_storage_conf,
)
from dazapiz._interactive import find_refresh_token
from dazapiz._refresh_token import as_refresh_token_info

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
    monkeypatch.setattr(dazapiz._credential.msal, "PublicClientApplication", FakeApp)
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
    monkeypatch.setattr(dazapiz._az_cli_token, "_is_windows", lambda: False)
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
    store.write("dazapiz.nocae", [bob])
    with pytest.raises(RefreshTokenNotFoundError) as err:
        find_refresh_token(OPTIONS, record_of(alice))
    assert SENTINEL not in shown(err.value)

    store.write("dazapiz.nocae", [alice, bob])
    cred = DeviceCodeCredential(authentication_record=record_of(alice))
    info = cred.get_refresh_token()
    assert info.token == SENTINEL
    assert SENTINEL not in shown(info)
    assert SENTINEL not in shown(cred)


def test_pasted_code_errors(monkeypatch):
    # The authorization code the user pasted is not echoed by any refusal.
    from test_pasted_code import REDIRECT, FakeApp

    import dazapiz._session

    cred = InteractiveBrowserCredential(redirect_uri=REDIRECT)
    app = FakeApp(error=ValueError("state mismatch: STATE-from-msal vs other"))
    monkeypatch.setattr(cred, "_get_app", lambda **kw: app)
    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: True)
    for reply in (f"{REDIRECT}?code={SENTINEL}&state=other", f"{REDIRECT}?code={SENTINEL}"):
        monkeypatch.setattr("builtins.input", lambda prompt="", reply=reply: reply)
        with pytest.raises(ClientAuthenticationError) as err:
            cred._request_token("User.Read")
        assert SENTINEL not in shown(err.value)


def test_az_login_prints_only_the_code_and_account_name(fake_az, monkeypatch, capsys):
    # Every field of the login JSON but the account name holds the sentinel (design §6).
    import json

    import dazapiz._session
    from dazapiz import az_login

    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: True)
    account = {
        "environmentName": SENTINEL,
        "homeTenantId": SENTINEL,
        "id": SENTINEL,
        "isDefault": True,
        "managedByTenants": [{"tenantId": SENTINEL}],
        "name": SENTINEL,
        "state": SENTINEL,
        "tenantId": SENTINEL,
        "user": {"name": "alice@contoso.com", "type": SENTINEL},
    }
    prompt = (
        "To sign in, use a web browser to open the page https://microsoft.com/devicelogin"
        " and enter the code F7GH2K9QX to authenticate."
    )
    fake_az.script("account show", [{"stderr": ["ERROR: Please run 'az login'"], "exit": 1}])
    fake_az.script("login", {"stderr": [prompt], "stdout": json.dumps([account])})
    assert az_login() == account
    fake_az.script("account show", {"stdout": json.dumps(account)})
    assert az_login() == account
    out, err = capsys.readouterr()
    assert SENTINEL not in out + err
    assert "F7GH2K9QX" in out
    assert out.count("alice@contoso.com") == 2


def test_api_client_never_logs_or_shows_the_bearer_token(monkeypatch, caplog, capsys):
    # verbose=True, a body posted, a failure with a body: no Authorization value anywhere.
    import logging
    import time

    import httpx
    from azure.core.credentials import AccessToken
    from recording_transport import RecordingTransport, json_response

    from dazapiz import ApiClient, ApiError
    from dazapiz._api_client import BearerAuth

    class Credential:
        def get_token(self, *scopes, **kwargs):
            return AccessToken(SENTINEL, int(time.time()) + 3600)

    transport = RecordingTransport(
        [
            json_response(200, {"ok": True}),
            httpx.Response(503),
            json_response(401, {"error": "unauthorized"}),
        ]
    )
    log = logging.getLogger("dazapiz.http")
    monkeypatch.setattr(log, "handlers", [])
    monkeypatch.setattr(log, "level", logging.NOTSET)
    client = ApiClient(
        "https://api.example.com",
        credential=Credential(),
        verbose=True,
        transport=transport,
        sleep=lambda s: None,
    )
    with caplog.at_level(logging.DEBUG):
        client.fetch("/x", "POST", json={"a": 1})
        with pytest.raises(ApiError) as err:
            client.fetch("/y")
    assert all(r.headers["authorization"] == f"Bearer {SENTINEL}" for r in transport.requests)
    assert caplog.records
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
    out, errout = capsys.readouterr()
    assert SENTINEL not in out + errout
    assert SENTINEL not in shown(err.value)
    assert SENTINEL not in shown(client)
    assert SENTINEL not in shown(client._http.auth)
    assert SENTINEL not in shown(BearerAuth(Credential(), "s"))


def test_app_credential_never_logs_or_shows_the_client_secret(monkeypatch, caplog, capsys):
    import logging

    from dazapiz import ApiClient, app_credential

    for name in ("AZURE_TOKEN_CREDENTIALS", "AZURE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ID", "cid")
    monkeypatch.setenv("APP_SECRET", SENTINEL)
    monkeypatch.setenv("APP_TENANT", "tid")
    log = logging.getLogger("dazapiz.http")
    monkeypatch.setattr(log, "handlers", [])
    monkeypatch.setattr(log, "level", logging.NOTSET)

    class Api(ApiClient):
        host_url = "https://api.example.com"
        client_id_env = "APP_ID"
        client_secret_env = "APP_SECRET"
        tenant_id_env = "APP_TENANT"

    with caplog.at_level(logging.DEBUG):
        client = Api(verbose=True)
        cred = app_credential("APP_ID", "APP_SECRET", tenant_id_env="APP_TENANT", mode="prod")
    assert any("ClientSecretCredential" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
    out, errout = capsys.readouterr()
    assert SENTINEL not in out + errout
    assert SENTINEL not in shown(client)
    assert SENTINEL not in shown(cred)

    # The partly set and unknown-mode errors name variables, never values.
    for env, mode in (("APP_ID", None), ("APP_TENANT", "client_secret"), (None, "bogus")):
        with pytest.MonkeyPatch.context() as mp:
            if env:
                mp.delenv(env)
            with pytest.raises(ValueError) as err:
                app_credential("APP_ID", "APP_SECRET", tenant_id_env="APP_TENANT", mode=mode)
        assert SENTINEL not in shown(err.value)


def test_duckdb_helpers_never_show_the_secret(azure_extension, caplog, capsys):
    # The token, the client secret and a credential's access token stay out
    # of logs, output, list_secrets() and the error of a failed CREATE SECRET.
    import logging
    import time

    duckdb = pytest.importorskip("duckdb")
    from azure.core.credentials import AccessToken

    import dazapiz.duckdb as dd

    class Credential:
        def get_token(self, *scopes, **kwargs):
            return AccessToken(SENTINEL + "-at", int(time.time()) + 3600)

    conn = duckdb.connect()
    with caplog.at_level(logging.DEBUG, logger="dazapiz.duckdb"):
        dd.set_token_secret(conn, SENTINEL, account="acct")
        dd.set_sp_secret(conn, "tid", "cid", SENTINEL + "'q", account="b")
        assert dd.set_credential_secret(conn, Credential())
        listed = repr(dd.list_secrets(conn).fetchall())

    class Failing:
        """A connection whose CREATE SECRET fails with the statement in the message."""

        def __init__(self, c):
            self._c = c

        def execute(self, sql, *args):
            if sql.startswith("CREATE"):
                raise duckdb.ParserException(f"syntax error at or near {sql}")
            return self._c.execute(sql, *args)

    failing = Failing(conn)
    errors = []
    for call in (
        lambda: dd.set_token_secret(failing, SENTINEL),
        lambda: dd.set_sp_secret(failing, "t", "c", SENTINEL + "'q"),
        lambda: dd.set_credential_secret(failing, Credential()),
    ):
        with pytest.raises(duckdb.ParserException) as err:
            call()
        errors.append(err.value)
    conn.close()

    assert caplog.records
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
    out, errout = capsys.readouterr()
    assert SENTINEL not in out + errout + listed
    for error in errors:
        assert "syntax error" in str(error)
        assert SENTINEL not in shown(error)
        # The original error, which carries the statement, is not chained
        # into the traceback.
        assert error.__cause__ is None
        assert error.__suppress_context__


def test_static_token_credential_never_shows_the_token():
    from dazapiz.testing import StaticTokenCredential

    cred = StaticTokenCredential(SENTINEL)
    cred.get_token("api://x/.default")
    assert SENTINEL not in shown(cred)
    assert SENTINEL not in shown([cred, {"k": cred}])
    assert "StaticTokenCredential(" in repr(cred)
