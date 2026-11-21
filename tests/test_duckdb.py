"""dazure.duckdb against a real in-memory DuckDB with the azure extension (design §4.5).

The oracle is DuckDB itself: what `duckdb_secrets()` and `duckdb_settings()`
report after each helper ran. `INSTALL azure` is the only network call, and
CI caches the extension directory so it happens once per DuckDB version.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest
from azure.core.credentials import AccessToken

duckdb = pytest.importorskip("duckdb", reason="needs the duckdb extra")

import dazure.duckdb as dd  # noqa: E402

PREFIXES = ("abfss://", "abfs://", "az://", "azure://")


def scopes(account: str) -> list[str]:
    if "." in account:
        return [p + account + "/" for p in PREFIXES]
    return [
        f"abfss://{account}.dfs.core.windows.net/",
        f"abfs://{account}.dfs.core.windows.net/",
        f"az://{account}.blob.core.windows.net/",
        f"azure://{account}.blob.core.windows.net/",
    ]


def secret(conn, name: str) -> dict:
    """One row of duckdb_secrets(redact=false), its secret_string split into fields."""
    rows = conn.execute(
        "SELECT name, type, provider, scope, secret_string "
        "FROM duckdb_secrets(redact=false) WHERE name = ?",
        [name],
    ).fetchall()
    assert len(rows) == 1, rows
    name, type_, provider, scope, string = rows[0]
    # key=value pairs joined by ";"; a part without "=" continues the value
    # before it (a CHAIN of several entries).
    fields: dict[str, str] = {}
    key = None
    for part in string.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
        else:
            fields[key] += ";" + part
    return {**fields, "name": name, "type": type_, "provider": provider, "scope": scope}


def default_scope(conn) -> list[str]:
    """The scope DuckDB gives an azure secret created without SCOPE."""
    conn.execute(
        "CREATE OR REPLACE SECRET ref (TYPE azure, PROVIDER access_token, ACCESS_TOKEN 'x')"
    )
    scope = secret(conn, "ref")["scope"]
    conn.execute("DROP SECRET ref")
    return scope


def setting(conn, name: str) -> str:
    return conn.execute("SELECT value FROM duckdb_settings() WHERE name = ?", [name]).fetchall()[0][
        0
    ]


@pytest.fixture
def conn(azure_extension):
    c = duckdb.connect(config={"allow_unredacted_secrets": True})
    yield c
    c.close()


# Secret names and scopes -------------------------------------------------------


@pytest.mark.parametrize(
    ("account", "name"),
    [
        (None, "dazure_default"),
        ("myacct", "dazure_myacct"),
        ("myacct.dfs.core.windows.net", "dazure_myacct_dfs_core_windows_net"),
        ("My-Acct", "dazure_my_acct"),
    ],
)
def test_token_secret(conn, account, name):
    dd.set_token_secret(conn, "tok", account=account)
    s = secret(conn, name)
    assert (s["type"], s["provider"], s["access_token"]) == ("azure", "access_token", "tok")
    # quak gives the access_token provider no ACCOUNT_NAME.
    assert "account_name" not in s
    assert s["scope"] == (default_scope(conn) if account is None else scopes(account))


@pytest.mark.parametrize("account", [None, "myacct", "myacct.dfs.core.windows.net"])
def test_sp_secret(conn, account):
    dd.set_sp_secret(conn, "tid", "cid", "csecret", account=account)
    s = secret(conn, dd._secret_name(account))
    assert s["provider"] == "service_principal"
    assert (s["tenant_id"], s["client_id"], s["client_secret"]) == ("tid", "cid", "csecret")
    if account is None:
        assert "account_name" not in s
        assert s["scope"] == default_scope(conn)
    else:
        assert s["account_name"] == account
        assert s["scope"] == scopes(account)


@pytest.mark.parametrize(
    ("chain", "expected"),
    [("default", "default"), (["cli", "env"], "cli;env"), (None, None)],
)
@pytest.mark.parametrize("account", [None, "myacct"])
def test_chain_secret(conn, account, chain, expected):
    dd.set_chain_secret(conn, account=account, chain=chain)
    s = secret(conn, dd._secret_name(account))
    assert s["provider"] == "credential_chain"
    assert s.get("chain") == expected
    if account is None:
        assert "account_name" not in s
        assert s["scope"] == default_scope(conn)
    else:
        assert s["account_name"] == account
        assert s["scope"] == scopes(account)


def test_secret_is_replaced(conn):
    dd.set_token_secret(conn, "one", account="a")
    dd.set_token_secret(conn, "two", account="a")
    assert secret(conn, "dazure_a")["access_token"] == "two"


def test_list_secrets(conn):
    dd.set_token_secret(conn, "tok")
    dd.set_sp_secret(conn, "tid", "cid", "csecret", account="b")
    conn.execute("CREATE SECRET other (TYPE s3, KEY_ID 'k', SECRET 's')")
    rel = dd.list_secrets(conn)
    assert rel.columns[:3] == ["name", "type", "provider"]
    rows = rel.fetchall()
    assert [r[0] for r in rows] == ["dazure_b", "dazure_default"]
    # Redacted by DuckDB even on a connection that allows unredacted secrets.
    assert all("csecret" not in r[-1] and "tok;" not in r[-1] for r in rows)


# Quoting -----------------------------------------------------------------------

AWKWARD = "a'b''c\\d\\'e\"f\n g é"


def test_values_round_trip(conn):
    dd.set_sp_secret(conn, AWKWARD + "t", AWKWARD + "c", AWKWARD + "s", account=AWKWARD)
    s = secret(conn, dd._secret_name(AWKWARD))
    assert s["tenant_id"] == AWKWARD + "t"
    assert s["client_id"] == AWKWARD + "c"
    assert s["client_secret"] == AWKWARD + "s"
    assert s["account_name"] == AWKWARD
    assert s["scope"] == scopes(AWKWARD)
    dd.set_token_secret(conn, AWKWARD)
    assert secret(conn, "dazure_default")["access_token"] == AWKWARD
    dd.set_chain_secret(conn, account="x", chain=["cli", AWKWARD])
    raw = conn.execute(
        "SELECT secret_string FROM duckdb_secrets(redact=false) WHERE name = 'dazure_x'"
    ).fetchall()[0][0]
    assert f";chain=cli;{AWKWARD}" in raw


def test_injection_stays_a_value(conn):
    evil = "x', ACCOUNT_NAME 'evil') ; DROP SECRET keep; --"
    conn.execute("CREATE SECRET keep (TYPE s3, KEY_ID 'k', SECRET 's')")
    dd.set_sp_secret(conn, evil, "cid", "s")
    keep = conn.execute("SELECT count(*) FROM duckdb_secrets() WHERE name = 'keep'").fetchall()
    assert keep == [(1,)]
    raw = conn.execute(
        "SELECT secret_string FROM duckdb_secrets(redact=false) WHERE name = 'dazure_default'"
    ).fetchall()[0][0]
    assert f"tenant_id={evil}" in raw
    assert "account_name" not in raw


def test_nul_refused(conn):
    with pytest.raises(ValueError, match="NUL"):
        dd.set_token_secret(conn, "a\x00b")


@pytest.mark.parametrize("bad", ["", None, 3])
def test_bad_values_refused(conn, bad):
    with pytest.raises((ValueError, TypeError)):
        dd.set_token_secret(conn, bad)
    with pytest.raises((ValueError, TypeError)):
        dd.set_sp_secret(conn, "t", bad, "s")
    with pytest.raises((ValueError, TypeError)):
        dd.set_chain_secret(conn, chain=[bad])
    if bad is not None:
        with pytest.raises((ValueError, TypeError)):
            dd.set_token_secret(conn, "tok", account=bad)


# set_credential_secret ---------------------------------------------------------


class FakeCredential:
    def __init__(self, token: str, expires_on: int) -> None:
        self.token = AccessToken(token, expires_on)
        self.scopes: list[tuple] = []

    def get_token(self, *scopes, **kwargs):
        self.scopes.append(scopes)
        return self.token


def test_credential_secret(conn):
    expires = int(time.time()) + 3600
    cred = FakeCredential("access-tok", expires)
    assert dd.set_credential_secret(conn, cred, account="myacct") == expires
    assert cred.scopes == [("https://storage.azure.com/.default",)]
    s = secret(conn, "dazure_myacct")
    assert (s["provider"], s["access_token"]) == ("access_token", "access-tok")
    assert s["scope"] == scopes("myacct")


def test_credential_secret_scope_and_replace(conn):
    cred = FakeCredential("one", 100)
    assert dd.set_credential_secret(conn, cred, scope="https://x/.default") == 100
    assert cred.scopes == [("https://x/.default",)]
    assert dd.set_credential_secret(conn, FakeCredential("two", 200)) == 200
    assert secret(conn, "dazure_default")["access_token"] == "two"
    assert dd.STORAGE_SCOPE == "https://storage.azure.com/.default"


def test_credential_secret_wants_a_token_credential(conn):
    with pytest.raises(TypeError, match="RefreshTokenCredential"):
        dd.set_credential_secret(conn, "a-refresh-token")


# Settings ----------------------------------------------------------------------


def test_tune(conn):
    dd.tune(
        conn,
        concurrency=8,
        chunk_size=2097152,
        buffer_size="4194304",
        transport="curl",
        metadata_cache=True,
        context_cache=False,
    )
    assert setting(conn, "azure_read_transfer_concurrency") == "8"
    assert setting(conn, "azure_read_transfer_chunk_size") == "2097152"
    assert setting(conn, "azure_read_buffer_size") == "4194304"
    assert setting(conn, "azure_transport_option_type") == "curl"
    assert setting(conn, "enable_http_metadata_cache") == "true"
    assert setting(conn, "azure_context_caching") in ("0", "false")


def test_tune_none_leaves_settings(conn):
    dd.tune(conn)  # loads the extension, so the settings exist
    before = conn.execute("SELECT name, value FROM duckdb_settings() ORDER BY name").fetchall()
    dd.tune(conn, concurrency=None, transport=None)
    assert (
        conn.execute("SELECT name, value FROM duckdb_settings() ORDER BY name").fetchall() == before
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"concurrency": 0},
        {"concurrency": 1.5},
        {"concurrency": True},
        {"chunk_size": -1},
        {"buffer_size": ""},
        {"transport": 3},
        {"metadata_cache": "yes"},
        {"context_cache": 1},
    ],
)
def test_tune_refuses(conn, kwargs):
    with pytest.raises((ValueError, TypeError)):
        dd.tune(conn, **kwargs)


def test_tune_names_the_setting_duckdb_refused(conn):
    with pytest.raises(duckdb.Error, match="azure_read_buffer_size"):
        dd.tune(conn, buffer_size="16MB")


def test_tune_warns_buffer_not_multiple_of_chunk(conn):
    with pytest.warns(UserWarning, match="multiple"):
        dd.tune(conn, chunk_size=3000000, buffer_size=4000000)
    dd.tune(conn, chunk_size=1000000, buffer_size=4000000)  # no warning


def test_azure_settings(conn):
    dd.tune(conn, concurrency=7)
    rel = dd.azure_settings(conn)
    assert rel.columns == ["name", "value", "description"]
    rows = {r[0]: r[1] for r in rel.fetchall()}
    expected = conn.execute(
        "SELECT name, value FROM duckdb_settings() WHERE name LIKE '%azure%'"
    ).fetchall()
    assert rows == dict(expected)
    assert rows["azure_read_transfer_concurrency"] == "7"


# The extension and the extra ---------------------------------------------------


def test_extension_loaded_only_once(conn):
    executed: list[str] = []

    class Spy:
        def __init__(self, c):
            self._c = c

        def execute(self, sql, *args):
            executed.append(sql)
            return self._c.execute(sql, *args)

        def sql(self, sql, *args):
            executed.append(sql)
            return self._c.sql(sql, *args)

    spy = Spy(conn)
    dd.set_token_secret(spy, "t")
    assert sum("LOAD azure" in s for s in executed) == 1
    executed.clear()
    dd.set_token_secret(spy, "t")
    dd.tune(spy, concurrency=2)
    assert not any("LOAD azure" in s or "INSTALL azure" in s for s in executed)


def test_missing_extra_names_the_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "duckdb", None)
    for call in (
        lambda: dd.set_token_secret(object(), "t"),
        lambda: dd.list_secrets(object()),
        lambda: dd.tune(object(), concurrency=1),
    ):
        with pytest.raises(ImportError, match=r"pip install 'dazure\[duckdb\]'"):
            call()


def test_import_dazure_does_not_import_duckdb():
    code = "import sys, dazure, dazure.duckdb; assert 'duckdb' not in sys.modules, 'imported'"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_empty_chain_refused(conn):
    with pytest.raises(ValueError, match="at least one"):
        dd.set_chain_secret(conn, chain=[])
    assert dd.list_secrets(conn).fetchall() == []
