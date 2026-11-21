"""DuckDB Azure secrets and tuning (design §4.5).

Ported from `quak`'s `az_set_*_secret()`, `az_list_secrets()`,
`az_conn_settings()` and `az_tune()`. Needs the `duckdb` extra: `duckdb` is
imported inside each function, so `import dazure` never needs it.

Each helper takes a DuckDB connection, runs `INSTALL azure; LOAD azure` if
the extension is not loaded yet, and executes the `CREATE OR REPLACE SECRET`
statement `quak` runs. Values are written as DuckDB string literals (quotes
doubled, nothing else special), because DuckDB before 1.2 cannot bind
parameters in `CREATE SECRET` (D45).

Secrets are named `dazure_default`, or `dazure_<account>` with every
character other than a letter or digit replaced by `_` and lower-cased
(D44), so they never collide with `quak`'s `quak_*` secrets in a shared
DuckDB file. With `account`, a secret is scoped to the account's
`abfss://`, `abfs://`, `az://` and `azure://` hosts, which DuckDB matches
as plain string prefixes against the URL. Delta tables never match an
account-scoped secret, so register an unscoped one for them.
"""

from __future__ import annotations

import logging
import re
import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import duckdb
    from azure.core.credentials import TokenCredential

__all__ = [
    "STORAGE_SCOPE",
    "azure_settings",
    "list_secrets",
    "set_chain_secret",
    "set_credential_secret",
    "set_sp_secret",
    "set_token_secret",
    "tune",
]

STORAGE_SCOPE = "https://storage.azure.com/.default"

_log = logging.getLogger("dazure.duckdb")
_REDACTED = "<redacted>"


def _duckdb():
    try:
        import duckdb
    except ImportError as err:
        raise ImportError(
            "dazure.duckdb needs DuckDB: pip install 'dazure[duckdb]'", name="duckdb"
        ) from err
    return duckdb


def _ensure_azure(conn: duckdb.DuckDBPyConnection) -> None:
    """`INSTALL azure; LOAD azure`, each only if needed."""
    # fetchall(): DuckDB 2 refuses further work while a result is unfinished.
    rows = conn.execute(
        "SELECT installed, loaded FROM duckdb_extensions() WHERE extension_name = 'azure'"
    ).fetchall()
    installed, loaded = rows[0] if rows else (False, False)
    if loaded:
        return
    if not installed:
        conn.execute("INSTALL azure")
    conn.execute("LOAD azure")


def _check_str(value: Any, arg: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"`{arg}` must be a string, not {type(value).__name__}.")
    if not value:
        raise ValueError(f"`{arg}` must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"`{arg}` must not contain a NUL character.")
    return value


def _literal(value: str) -> str:
    """A DuckDB string literal: single quotes doubled; backslashes are literal."""
    return "'" + value.replace("'", "''") + "'"


def _secret_name(account: str | None) -> str:
    if account is None:
        return "dazure_default"
    _check_str(account, "account")
    return "dazure_" + re.sub(r"[^a-zA-Z0-9]", "_", account).lower()


def _account_scopes(account: str) -> list[str]:
    """`quak`'s `az_account_scopes()`: the account's host under each scheme."""
    if "." in account:
        # Already a fully qualified host; used verbatim for every scheme.
        return [f"{scheme}{account}/" for scheme in ("abfss://", "abfs://", "az://", "azure://")]
    return [
        f"abfss://{account}.dfs.core.windows.net/",
        f"abfs://{account}.dfs.core.windows.net/",
        f"az://{account}.blob.core.windows.net/",
        f"azure://{account}.blob.core.windows.net/",
    ]


def _create_secret(
    conn: duckdb.DuckDBPyConnection,
    provider: str,
    options: list[tuple[str, str]],
    account: str | None,
    *,
    account_name: bool,
    secrets: Sequence[str] = (),
) -> str:
    """Run `CREATE OR REPLACE SECRET`; an error never carries a secret value."""
    duckdb = _duckdb()
    name = _secret_name(account)
    if account is not None:
        if account_name:
            options = [*options, ("ACCOUNT_NAME", _literal(account))]
        scope = ", ".join(_literal(s) for s in _account_scopes(account))
        options = [*options, ("SCOPE", f"({scope})")]
    clauses = "".join(f",\n  {key} {value}" for key, value in options)
    sql = f"CREATE OR REPLACE SECRET {name} (\n  TYPE azure,\n  PROVIDER {provider}{clauses}\n)"
    _ensure_azure(conn)
    try:
        conn.execute(sql)
    except duckdb.Error as err:
        message = str(err)
        for value in secrets:
            for form in (value, value.replace("'", "''")):
                message = message.replace(form, _REDACTED)
        raise type(err)(message) from None
    if account is None:
        _log.info("Registered DuckDB Azure secret %s (%s).", name, provider)
    else:
        _log.info("Registered DuckDB Azure secret %s (%s) for %r.", name, provider, account)
    return name


def set_token_secret(
    conn: duckdb.DuckDBPyConnection, token: str, account: str | None = None
) -> None:
    """Register an access token as a DuckDB Azure secret.

    As `quak::az_set_token_secret()`: `CREATE OR REPLACE SECRET` with
    `PROVIDER access_token`. With `account`, the secret is scoped to that
    account's hosts (bare name or fully qualified host) and applies to
    Parquet, CSV and JSON reads; Delta tables never match an account-scoped
    secret, so register an unscoped one for them. The token expires and is
    not refreshed: see `set_credential_secret()`.
    """
    _check_str(token, "token")
    _create_secret(
        conn,
        "access_token",
        [("ACCESS_TOKEN", _literal(token))],
        account,
        account_name=False,
        secrets=[token],
    )


def set_credential_secret(
    conn: duckdb.DuckDBPyConnection,
    credential: TokenCredential,
    account: str | None = None,
    scope: str = STORAGE_SCOPE,
) -> int:
    """Register an access token from any `TokenCredential` as a DuckDB Azure secret.

    Calls `credential.get_token(scope)` and registers the token as
    `set_token_secret()` does. This is how an `az login` refresh token
    reaches DuckDB, which its own `credential_chain` cannot do:
    `set_credential_secret(conn, RefreshTokenCredential(refresh_token_from_az_cli()))`.

    Returns the token's `expires_on` (seconds since the epoch). The secret is
    not refreshed in the background; call again before then to replace it.
    Delta tables never match an account-scoped secret, so register an
    unscoped one for them.
    """
    if not callable(getattr(credential, "get_token", None)):
        raise TypeError(
            "`credential` must be a TokenCredential; for a refresh token, pass "
            "RefreshTokenCredential(refresh_token)."
        )
    _check_str(scope, "scope")
    access = credential.get_token(scope)
    set_token_secret(conn, access.token, account)
    return access.expires_on


def set_sp_secret(
    conn: duckdb.DuckDBPyConnection,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    account: str | None = None,
) -> None:
    """Register a service principal as a DuckDB Azure secret.

    As `quak::az_set_sp_secret()`: `PROVIDER service_principal`, so DuckDB
    redeems the client secret itself. With `account`, the secret also gets
    `ACCOUNT_NAME` and is scoped to that account's hosts; Delta tables never
    match an account-scoped secret, so register an unscoped one for them.
    """
    _check_str(tenant_id, "tenant_id")
    _check_str(client_id, "client_id")
    _check_str(client_secret, "client_secret")
    _create_secret(
        conn,
        "service_principal",
        [
            ("TENANT_ID", _literal(tenant_id)),
            ("CLIENT_ID", _literal(client_id)),
            ("CLIENT_SECRET", _literal(client_secret)),
        ],
        account,
        account_name=True,
        secrets=[client_secret],
    )


def set_chain_secret(
    conn: duckdb.DuckDBPyConnection,
    account: str | None = None,
    chain: str | Sequence[str] | None = "default",
) -> None:
    """Register a DuckDB credential-chain secret, which DuckDB resolves itself.

    As `quak::az_set_chain_secret()`: `PROVIDER credential_chain`. `chain` is
    one entry or several (joined with `;`), such as `"cli"` or
    `["managed_identity", "env"]`; `None` leaves `CHAIN` out. With `account`,
    the secret also gets `ACCOUNT_NAME` and is scoped to that account's
    hosts; Delta tables never match an account-scoped secret, so register an
    unscoped one for them.
    """
    options = []
    if chain is not None:
        entries = [chain] if isinstance(chain, str) else list(chain)
        if not entries:
            raise ValueError("`chain` must name at least one entry, or be None.")
        for entry in entries:
            _check_str(entry, "chain")
        options.append(("CHAIN", _literal(";".join(entries))))
    _create_secret(conn, "credential_chain", options, account, account_name=True)


def list_secrets(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """The connection's Azure secrets, as `quak::az_list_secrets()`.

    A relation over `duckdb_secrets()` where `type = 'azure'`, ordered by
    name; DuckDB redacts the secret values. Fetch it with `.fetchall()`,
    `.df()` or `.pl()`, or print it.
    """
    _duckdb()
    _ensure_azure(conn)
    return conn.sql("SELECT * FROM duckdb_secrets() WHERE type = 'azure' ORDER BY name")


def azure_settings(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """The connection's Azure settings, as `quak::az_conn_settings()`.

    A relation of `name`, `value` and `description` from `duckdb_settings()`
    for every setting whose name contains `azure`.
    """
    _duckdb()
    _ensure_azure(conn)
    return conn.sql(
        "SELECT name, value, description FROM duckdb_settings() WHERE name LIKE '%azure%'"
    )


def _check_positive_int(value: Any, arg: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{arg}` must be a positive integer or None.")
    if value <= 0:
        raise ValueError(f"`{arg}` must be a positive integer or None.")


def _check_size(value: Any, arg: str) -> None:
    if isinstance(value, str):
        _check_str(value, arg)
    else:
        _check_positive_int(value, arg)


def _check_bool(value: Any, arg: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"`{arg}` must be True, False or None.")


def _as_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def tune(
    conn: duckdb.DuckDBPyConnection,
    *,
    concurrency: int | None = None,
    chunk_size: int | str | None = None,
    buffer_size: int | str | None = None,
    transport: str | None = None,
    metadata_cache: bool | None = None,
    context_cache: bool | None = None,
) -> None:
    """Set the Azure read and transport settings, as `quak::az_tune()`.

    Each argument left `None` leaves its setting unchanged:

    | Argument | DuckDB setting |
    | --- | --- |
    | `concurrency` | `azure_read_transfer_concurrency` |
    | `chunk_size` | `azure_read_transfer_chunk_size` (bytes) |
    | `buffer_size` | `azure_read_buffer_size` (bytes) |
    | `transport` | `azure_transport_option_type` (`"default"`, `"curl"`) |
    | `metadata_cache` | `enable_http_metadata_cache` |
    | `context_cache` | `azure_context_caching` |

    Warns, as `quak` does, when the buffer size is not a multiple of the
    chunk size. A value DuckDB refuses raises its error, prefixed with the
    setting's name.
    """
    if concurrency is not None:
        _check_positive_int(concurrency, "concurrency")
    if chunk_size is not None:
        _check_size(chunk_size, "chunk_size")
    if buffer_size is not None:
        _check_size(buffer_size, "buffer_size")
    if transport is not None:
        _check_str(transport, "transport")
    if metadata_cache is not None:
        _check_bool(metadata_cache, "metadata_cache")
    if context_cache is not None:
        _check_bool(context_cache, "context_cache")

    duckdb = _duckdb()
    _ensure_azure(conn)

    if buffer_size is not None:
        if chunk_size is None:
            current = conn.execute(
                "SELECT value FROM duckdb_settings() WHERE name = 'azure_read_transfer_chunk_size'"
            ).fetchall()
            chunk = _as_number(current[0][0]) if current else None
        else:
            chunk = _as_number(chunk_size)
        buffer = _as_number(buffer_size)
        if chunk and buffer and buffer % chunk:
            warnings.warn(
                f"The Azure read buffer size ({buffer}) is not a multiple of the "
                f"transfer chunk size ({chunk}).",
                UserWarning,
                stacklevel=2,
            )

    for name, value in (
        ("azure_read_transfer_concurrency", concurrency),
        ("azure_read_transfer_chunk_size", chunk_size),
        ("azure_read_buffer_size", buffer_size),
        ("azure_transport_option_type", transport),
        ("enable_http_metadata_cache", metadata_cache),
        ("azure_context_caching", context_cache),
    ):
        if value is None:
            continue
        try:
            # The name is one of the six above; the value is bound.
            conn.execute(f"SET {name} = ?", [value])
        except duckdb.Error as err:
            raise type(err)(f"{name}: {err}") from err
