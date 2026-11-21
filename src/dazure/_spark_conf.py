"""Spark / Hadoop ABFS configuration (design §4.4).

A port of `azr::azure_spark_storage_conf()`, key for key when arguments are
passed explicitly (tested against a fixture generated from azr). The
defaults differ from azr's where §4.4 says.
"""

from __future__ import annotations

import re
from typing import Literal, cast

from ._refresh_token import SupportsRefreshToken, as_refresh_token_info, env

__all__ = ["SparkStorageConf", "spark_storage_conf"]

AuthType = Literal[
    "refresh_token", "client_secret", "workload_identity", "managed_identity", "shared_key"
]
_AUTH_TYPES = (
    "refresh_token",
    "client_secret",
    "workload_identity",
    "managed_identity",
    "shared_key",
)

_PUBLIC_CLOUD = "login.microsoftonline.com"
_PROVIDER = "org.apache.hadoop.fs.azurebfs.oauth2."
_BASE = "fs.azure.account."
_REDACTED = "<redacted>"

# Authority host -> DFS endpoint suffix of the matching cloud; anything else is public.
_DFS_SUFFIX = {
    "login.microsoftonline.us": "dfs.core.usgovcloudapi.net",
    "login.chinacloudapi.cn": "dfs.core.chinacloudapi.cn",
}
_DFS_PUBLIC = "dfs.core.windows.net"

# azr's validate_tenant_id().
_TENANT_RE = re.compile(r"[A-Za-z0-9.-]+")

# Properties whose values are secrets.
_SECRET_PROPERTIES = ("oauth2.client.secret", "oauth2.refresh.token", "key")


def _is_secret_key(key: str, value: object) -> bool:
    i = key.find(_BASE)
    if i < 0:
        return False
    prop = key[i + len(_BASE) :]
    for secret in _SECRET_PROPERTIES:
        if prop == secret or prop.startswith(secret + "."):
            # `oauth2.refresh.token.endpoint` starts like the refresh token, and so
            # does the refresh token of an account named "endpoint"; the
            # endpoint's value is the token URL, a token never is.
            is_endpoint = (
                secret == "oauth2.refresh.token"
                and prop.startswith("oauth2.refresh.token.endpoint")
                and isinstance(value, str)
                and value.startswith("https://")
            )
            return not is_endpoint
    return False


class SparkStorageConf(dict[str, str]):
    """The `fs.azure.*` keys of `spark_storage_conf()`, as a plain `dict[str, str]`.

    The dict holds the real values, to pass to
    `SparkSession.builder.config(map=conf)` or `spark.conf.set()`; `repr()` and
    `str()` show `<redacted>` for the client secret, refresh token and account
    key, so printing one in a notebook does not leak them. `copy()` and `|`
    keep the type, and so the redaction.

    Examples
    --------
    ```python
    conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
    conf  # SparkStorageConf({..., 'spark.hadoop.fs.azure.account.oauth2.refresh.token': '<redacted>', ...})
    for key, value in conf.items():
        spark.conf.set(key, value)
    ```
    """

    def _redacted(self) -> dict[str, str]:
        return {k: _REDACTED if _is_secret_key(k, v) else v for k, v in self.items()}

    def __repr__(self) -> str:
        """The keys with the client secret, refresh token and account key redacted."""
        return f"{type(self).__name__}({self._redacted()!r})"

    __str__ = __repr__

    def copy(self) -> SparkStorageConf:
        """A shallow copy, still a `SparkStorageConf`."""
        return type(self)(self)

    def __or__(self, other: object) -> SparkStorageConf:
        """Merge with a dict, the dict's keys winning, into a `SparkStorageConf`."""
        if not isinstance(other, dict):
            return NotImplemented
        return type(self)({**self, **cast("dict[str, str]", other)})

    def __ror__(self, other: object) -> SparkStorageConf:
        """Merge a dict with this, this one's keys winning, into a `SparkStorageConf`."""
        if not isinstance(other, dict):
            return NotImplemented
        return type(self)({**cast("dict[str, str]", other), **self})


def _check_str(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str or None, not {type(value).__name__}")
    if not value:
        raise ValueError(f"{name} must not be empty")


def _normalize_host(authority_host: str) -> str:
    # As azr's normalize_authority_host(): drop trailing slashes, then the scheme.
    host = re.sub(r"^https?://", "", re.sub(r"/+$", "", authority_host))
    if not host:
        raise ValueError(f"authority_host {authority_host!r} has no host")
    return host


def check_tenant(tenant_id: str) -> None:
    if not _TENANT_RE.fullmatch(tenant_id):
        raise ValueError(f"tenant_id {tenant_id!r} is not a valid tenant ID")


def _required(value: str | None, arg: str, var: str, auth_type: str) -> str:
    value = value if value is not None else env(var)
    if value is None:
        raise ValueError(
            f"{arg} is required when auth_type is {auth_type!r}: pass it or set ${var}."
        )
    return value


def spark_storage_conf(
    auth_type: AuthType = "refresh_token",
    *,
    storage_account: str | None = None,
    tenant_id: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    refresh_token: str | SupportsRefreshToken | None = None,
    account_key: str | None = None,
    token_file: str | None = None,
    authority_host: str | None = None,
    prefix: str | None = "spark.hadoop",
) -> SparkStorageConf:
    """Build the Hadoop `fs.azure.*` keys that let Spark read ADLS Gen2.

    A port of `azr::azure_spark_storage_conf()`: with arguments passed
    explicitly the keys and values are azr's, key for key. With the default
    `prefix="spark.hadoop"` the result goes to `SparkSession.builder.config(map=...)`
    or a cluster's Spark config; `prefix=None` gives the raw `fs.azure.*` keys
    for `core-site.xml` or `hadoopConfiguration().set()`.

    Arguments another `auth_type` uses are ignored, as in azr. An empty
    environment variable counts as unset.

    Parameters
    ----------
    auth_type
        How Hadoop authenticates:

        - `"refresh_token"`: a delegated user (`RefreshTokenBasedTokenProvider`).
          Uses `refresh_token`; `client_id` and `tenant_id`, when passed, win
          over the token's own.
        - `"client_secret"`: a service principal (`ClientCredsTokenProvider`).
          `client_id`, `tenant_id` and `client_secret` default to
          `$AZURE_CLIENT_ID`, `$AZURE_TENANT_ID` and `$AZURE_CLIENT_SECRET`.
        - `"workload_identity"`: Kubernetes workload identity
          (`WorkloadIdentityTokenProvider`), with `client_id`, `tenant_id` and
          `token_file` from `$AZURE_CLIENT_ID`, `$AZURE_TENANT_ID` and
          `$AZURE_FEDERATED_TOKEN_FILE`, which the AKS webhook sets. Needs
          Hadoop 3.4.1+ (Spark 4.x, Databricks 14.3+ LTS, Synapse 3.4+).
        - `"managed_identity"`: IMDS (`MsiTokenProvider`). `client_id` (else
          `$AZURE_CLIENT_ID`) selects a user-assigned identity; without one the
          key is left out and Hadoop uses the system-assigned identity.
          `tenant_id` defaults to `$AZURE_TENANT_ID`, else `"common"`.
        - `"shared_key"`: the storage account key; needs `storage_account` and
          `account_key`.
    storage_account
        Scope every key to this account's DFS host. A short name is expanded
        with the DFS suffix of the cloud `authority_host` names (public, US
        Government or China); a name with a dot is used as is. Default: keys
        for every account.
    tenant_id
        The tenant (GUID or domain) whose token endpoint Hadoop calls.
    client_id
        The client (application) ID: the token's client for
        `"refresh_token"`, the service principal or identity otherwise.
    client_secret
        The service principal's secret, for `"client_secret"`.
    refresh_token
        For `"refresh_token"`: a string, a `SupportsRefreshToken` such as
        `refresh_token_from_az_cli()`, or `None` for `$AZURE_REFRESH_TOKEN`.
        A `SupportsRefreshToken` supplies its own client ID and tenant; a
        string takes `$AZURE_CLIENT_ID`, else `AZURE_CLI_CLIENT_ID`, and
        `$AZURE_TENANT_ID`, else `"common"`.
    account_key
        The storage account key, for `"shared_key"`.
    token_file
        The federated token file, for `"workload_identity"`.
    authority_host
        The Entra authority host; default `$AZURE_AUTHORITY_HOST`, else
        `login.microsoftonline.com`. May carry a scheme and trailing slash.
    prefix
        Prepended to every key with a dot; `None` for the raw Hadoop keys.

    Returns
    -------
    SparkStorageConf
        A `dict[str, str]` whose `repr` and `str` redact the secrets.

    Raises
    ------
    ValueError
        An unknown `auth_type`, an empty argument, a tenant ID that is not
        valid, or a value `auth_type` needs that is neither passed nor in its
        environment variable.
    TypeError
        An argument is not a string.
    RefreshTokenNotFoundError
        `auth_type="refresh_token"` with no `refresh_token` and no
        `$AZURE_REFRESH_TOKEN`.

    Notes
    -----
    Neither PySpark nor the Azure SDK builds these keys; Hadoop's ABFS
    driver redeems the token itself. Two details carried over from azr:
    `RefreshTokenBasedTokenProvider` reads `oauth2.refresh.token.endpoint`,
    not `oauth2.client.endpoint`, and the MSI authority needs its trailing
    `/`.

    Examples
    --------
    ```python
    from pyspark.sql import SparkSession
    from dazure import refresh_token_from_az_cli, spark_storage_conf

    conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
    spark = SparkSession.builder.config(map=conf).getOrCreate()
    spark.read.parquet("abfss://data@myaccount.dfs.core.windows.net/sales/")
    ```

    A service principal, for one account only:

    ```python
    conf = spark_storage_conf("client_secret", storage_account="myaccount")
    ```
    """
    if auth_type not in _AUTH_TYPES:
        raise ValueError(f"auth_type must be one of {', '.join(_AUTH_TYPES)}, not {auth_type!r}")
    for name, value in (
        ("prefix", prefix),
        ("storage_account", storage_account),
        ("tenant_id", tenant_id),
        ("client_id", client_id),
        ("client_secret", client_secret),
        ("account_key", account_key),
        ("token_file", token_file),
        ("authority_host", authority_host),
    ):
        if value is not None:
            _check_str(name, value)

    host = _normalize_host(authority_host or env("AZURE_AUTHORITY_HOST") or _PUBLIC_CLOUD)

    if storage_account is None:
        scope = ""
    elif "." in storage_account:
        scope = "." + storage_account
    else:
        scope = f".{storage_account}.{_DFS_SUFFIX.get(host, _DFS_PUBLIC)}"
    head = "" if prefix is None else prefix.rstrip(".") + "."

    def key(prop: str) -> str:
        return f"{head}{_BASE}{prop}{scope}"

    def token_url(tenant: str) -> str:
        return f"https://{host}/{tenant}/oauth2/v2.0/token"

    # Hadoop concatenates the MSI authority with the tenant, so it needs the "/".
    msi_authority = f"https://{host}/"

    if auth_type == "shared_key":
        if storage_account is None:
            raise ValueError("storage_account is required when auth_type is 'shared_key'.")
        if account_key is None:
            raise ValueError("account_key is required when auth_type is 'shared_key'.")
        return SparkStorageConf({key("auth.type"): "SharedKey", key("key"): account_key})

    if auth_type == "refresh_token":
        info = as_refresh_token_info(refresh_token)
        client_id = client_id if client_id is not None else info.client_id
        tenant_id = tenant_id if tenant_id is not None else info.tenant_id
        check_tenant(tenant_id)
        return SparkStorageConf(
            {
                key("auth.type"): "OAuth",
                key("oauth.provider.type"): _PROVIDER + "RefreshTokenBasedTokenProvider",
                key("oauth2.client.id"): client_id,
                key("oauth2.refresh.token"): info.token,
                # RefreshTokenBasedTokenProvider reads `refresh.token.endpoint`, not
                # `client.endpoint`; the latter is silently ignored for this flow.
                key("oauth2.refresh.token.endpoint"): token_url(tenant_id),
            }
        )

    if auth_type == "client_secret":
        client_id = _required(client_id, "client_id", "AZURE_CLIENT_ID", auth_type)
        tenant_id = _required(tenant_id, "tenant_id", "AZURE_TENANT_ID", auth_type)
        client_secret = _required(client_secret, "client_secret", "AZURE_CLIENT_SECRET", auth_type)
        check_tenant(tenant_id)
        return SparkStorageConf(
            {
                key("auth.type"): "OAuth",
                key("oauth.provider.type"): _PROVIDER + "ClientCredsTokenProvider",
                key("oauth2.client.id"): client_id,
                key("oauth2.client.secret"): client_secret,
                key("oauth2.client.endpoint"): token_url(tenant_id),
            }
        )

    if auth_type == "workload_identity":
        client_id = _required(client_id, "client_id", "AZURE_CLIENT_ID", auth_type)
        tenant_id = _required(tenant_id, "tenant_id", "AZURE_TENANT_ID", auth_type)
        token_file = _required(token_file, "token_file", "AZURE_FEDERATED_TOKEN_FILE", auth_type)
        check_tenant(tenant_id)
        return SparkStorageConf(
            {
                key("auth.type"): "OAuth",
                key("oauth.provider.type"): _PROVIDER + "WorkloadIdentityTokenProvider",
                key("oauth2.client.id"): client_id,
                key("oauth2.msi.tenant"): tenant_id,
                key("oauth2.token.file"): token_file,
                key("oauth2.msi.authority"): msi_authority,
            }
        )

    # managed_identity
    client_id = client_id if client_id is not None else env("AZURE_CLIENT_ID")
    tenant_id = tenant_id if tenant_id is not None else (env("AZURE_TENANT_ID") or "common")
    check_tenant(tenant_id)
    conf = {
        key("auth.type"): "OAuth",
        key("oauth.provider.type"): _PROVIDER + "MsiTokenProvider",
    }
    if client_id is not None:
        # Without it Hadoop asks IMDS for the system-assigned identity.
        conf[key("oauth2.client.id")] = client_id
    conf[key("oauth2.msi.tenant")] = tenant_id
    conf[key("oauth2.msi.authority")] = msi_authority
    return SparkStorageConf(conf)
