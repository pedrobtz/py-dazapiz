"""Checklist item 7: DuckDB reads with `set_credential_secret()` and `set_sp_secret()`.

Each secret is registered account-scoped and unscoped, on a fresh in-memory
connection, and reads the test file by its fully qualified `abfss://` URL.
`set_credential_secret()` uses the `az login` refresh token
(`RefreshTokenCredential(refresh_token_from_az_cli())`) on macOS and Linux,
and `AzureCliCredential` on Windows, where the CLI cache is not read.
Skipped unless `DAZURE_LIVE=1`; needs the `duckdb` extra.
"""

from __future__ import annotations

import sys
import time

import pytest

from dazure import RefreshTokenCredential, refresh_token_from_az_cli

SCOPED = pytest.mark.parametrize("scoped", [True, False], ids=["scoped", "unscoped"])


def _connect():
    duckdb = pytest.importorskip("duckdb", reason="needs the duckdb extra")
    return duckdb.connect()


def _read(conn, storage) -> int:
    account, container, path, rows = storage
    url = f"abfss://{account}.dfs.core.windows.net/{container}/{path}"
    count = conn.execute(f"SELECT count(*) FROM '{url}'").fetchall()[0][0]
    if rows is None:
        assert count >= 1
    else:
        assert count == rows
    return count


def _user_credential():
    if sys.platform == "win32":
        from azure.identity import AzureCliCredential

        return AzureCliCredential()
    return RefreshTokenCredential(refresh_token_from_az_cli())


@SCOPED
def test_read_with_credential_secret(storage, scoped):
    from dazure.duckdb import list_secrets, set_credential_secret

    conn = _connect()
    expires_on = set_credential_secret(conn, _user_credential(), storage[0] if scoped else None)
    assert expires_on > time.time() + 60
    assert list_secrets(conn).fetchall()
    _read(conn, storage)


@SCOPED
def test_read_with_sp_secret(storage, service_principal, scoped):
    from dazure.duckdb import list_secrets, set_sp_secret

    conn = _connect()
    tenant_id, client_id, client_secret = service_principal
    set_sp_secret(conn, tenant_id, client_id, client_secret, storage[0] if scoped else None)
    assert client_secret not in str(list_secrets(conn).fetchall())
    _read(conn, storage)
