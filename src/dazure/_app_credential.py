"""Per-API credentials: `app_credential()` (design §4.1.1)."""

from __future__ import annotations

import logging
import os
from typing import Literal, overload

from azure.core.credentials import TokenCredential
from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)

from . import _session
from ._interactive import DeviceCodeCredential

__all__ = ["app_credential"]

logger = logging.getLogger("dazure.http")

# dazure's names, and the azure-identity class names that
# `AZURE_TOKEN_CREDENTIALS` also takes (azr maps the same ones), lower-cased.
_MODES = {
    "dev": "dev",
    "prod": "prod",
    "client_secret": "client_secret",
    "clientsecretcredential": "client_secret",
    "environmentcredential": "client_secret",
    "workload_identity": "workload_identity",
    "workloadidentitycredential": "workload_identity",
    "managed_identity": "managed_identity",
    "managedidentitycredential": "managed_identity",
    "azure_cli": "azure_cli",
    "azureclicredential": "azure_cli",
    "device_code": "device_code",
    "devicecodecredential": "device_code",
}
_VALID = "'dev', 'prod', 'client_secret', 'workload_identity', 'managed_identity', 'azure_cli' or 'device_code'"


def _env(name: str) -> str | None:
    return os.environ.get(name) or None  # empty counts as unset (D25)


def app_credential(
    client_id_env: str,
    client_secret_env: str,
    *,
    tenant_id_env: str = "AZURE_TENANT_ID",
    mode: str | None = None,
) -> TokenCredential:
    """The credential an API's client uses, chosen from the environment now.

    `client_id_env`, `client_secret_env` and `tenant_id_env` name the variables
    that hold this API's service principal, so it can live in variables of
    its own (`APP_API_CLIENT_ID`, ...) rather than the machine's
    `AZURE_CLIENT_ID`. The mode is `mode`, else `$AZURE_TOKEN_CREDENTIALS`,
    else automatic, matched case-insensitively:

    | Mode | Credential |
    | --- | --- |
    | `"prod"` | `ClientSecretCredential` from the named variables when they are set, else `WorkloadIdentityCredential()` when `$AZURE_FEDERATED_TOKEN_FILE` is set, else `ManagedIdentityCredential()` (user-assigned with `client_id=$AZURE_CLIENT_ID` when that is set) |
    | `"dev"` | `ChainedTokenCredential(AzureCliCredential(), dazure.DeviceCodeCredential())`, the device code only in an interactive session (a TTY or a notebook kernel) |
    | `"client_secret"`, `"workload_identity"`, `"managed_identity"`, `"azure_cli"`, `"device_code"` (or the azure-identity class name) | that credential alone |
    | automatic | the named service principal when its client ID and secret variables are set, otherwise `"dev"` |

    Parameters
    ----------
    client_id_env
        The variable holding the service principal's client ID.
    client_secret_env
        The variable holding its client secret.
    tenant_id_env
        The variable holding its tenant ID.
    mode
        One of the modes above; default `$AZURE_TOKEN_CREDENTIALS`, else
        automatic.

    Returns
    -------
    azure.core.credentials.TokenCredential
        An azure-identity credential, unchanged; no token is fetched here.

    Raises
    ------
    ValueError
        An unknown mode; a client ID without its secret, or the reverse
        (naming the missing variable); a service principal with no tenant; or
        `"client_secret"` with neither variable set.

    Notes
    -----
    Every credential is an `azure-identity` class, built and returned as is;
    the choice is what dazure adds. Variables are read once, now; an empty
    variable counts as unset. The mode and credential class chosen (never a
    value) are logged on the `dazure.http` logger at `INFO`.

    Examples
    --------
    ```python
    from dazure import app_credential

    credential = app_credential("APP_API_CLIENT_ID", "APP_API_SECRET")
    token = credential.get_token("api://my-api/.default")
    ```
    """
    if mode is not None:
        source, raw = "mode", mode
    elif _env("AZURE_TOKEN_CREDENTIALS"):
        source, raw = "AZURE_TOKEN_CREDENTIALS", _env("AZURE_TOKEN_CREDENTIALS")
    else:
        source, raw = None, None
    names = (client_id_env, client_secret_env, tenant_id_env)
    client_id, secret, tenant = (_env(name) for name in names)

    if raw is None:
        chosen = "auto"
    else:
        chosen = _MODES.get(raw.strip().lower())
        if chosen is None:
            raise ValueError(f"Unknown credential mode {raw!r} (from {source}); use {_VALID}.")

    def service_principal() -> TokenCredential:
        sp_id, sp_secret, sp_tenant = _service_principal(
            names, client_id, secret, tenant, required=True
        )
        return ClientSecretCredential(tenant_id=sp_tenant, client_id=sp_id, client_secret=sp_secret)

    if chosen == "auto":
        if _service_principal(names, client_id, secret, tenant, required=False):
            chosen, credential = "client_secret", service_principal()
        else:
            chosen, credential = "dev", _dev()
    elif chosen == "prod":
        if _service_principal(names, client_id, secret, tenant, required=False):
            credential = service_principal()
        elif _env("AZURE_FEDERATED_TOKEN_FILE"):
            credential = WorkloadIdentityCredential()
        else:
            credential = _managed_identity()
    elif chosen == "dev":
        credential = _dev()
    elif chosen == "client_secret":
        credential = service_principal()
    elif chosen == "workload_identity":
        credential = WorkloadIdentityCredential()
    elif chosen == "managed_identity":
        credential = _managed_identity()
    elif chosen == "azure_cli":
        credential = AzureCliCredential()
    else:
        credential = DeviceCodeCredential()

    via = f" (from {source})" if source else " (automatic)"
    logger.info(
        "\N{INFORMATION SOURCE} Credential: %s, mode %s%s.", _describe(credential), chosen, via
    )
    return credential


@overload
def _service_principal(
    names: tuple[str, str, str],
    client_id: str | None,
    secret: str | None,
    tenant: str | None,
    *,
    required: Literal[True],
) -> tuple[str, str, str]: ...
@overload
def _service_principal(
    names: tuple[str, str, str],
    client_id: str | None,
    secret: str | None,
    tenant: str | None,
    *,
    required: bool,
) -> tuple[str, str, str] | None: ...
def _service_principal(
    names: tuple[str, str, str],
    client_id: str | None,
    secret: str | None,
    tenant: str | None,
    *,
    required: bool,
) -> tuple[str, str, str] | None:
    """The named service principal's (client ID, secret, tenant), or None if unset.

    A service principal set in part raises; with `required`, nothing set
    raises too. The message names the variables, never their values.
    """
    id_name, secret_name, tenant_name = names
    if client_id is None and secret is None:
        if required:
            raise ValueError(f"No service principal: {id_name} and {secret_name} are not set.")
        return None
    if client_id is None:
        raise ValueError(f"{secret_name} is set but {id_name} is not.")
    if secret is None:
        raise ValueError(f"{id_name} is set but {secret_name} is not.")
    if tenant is None:
        raise ValueError(f"{id_name} and {secret_name} are set but {tenant_name} is not.")
    return client_id, secret, tenant


def _managed_identity() -> TokenCredential:
    # As DefaultAzureCredential passes managed_identity_client_id: the standard
    # variable names a user-assigned identity (D10); unset or empty is system-assigned.
    return ManagedIdentityCredential(client_id=_env("AZURE_CLIENT_ID"))


def _dev() -> TokenCredential:
    if _session.is_interactive():
        return ChainedTokenCredential(AzureCliCredential(), DeviceCodeCredential())
    return ChainedTokenCredential(AzureCliCredential())


def _describe(credential: TokenCredential) -> str:
    if isinstance(credential, ChainedTokenCredential):
        inner = ", ".join(type(c).__name__ for c in credential.credentials)
        return f"ChainedTokenCredential({inner})"
    return type(credential).__name__
