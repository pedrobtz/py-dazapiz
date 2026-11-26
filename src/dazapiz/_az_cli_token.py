"""The `az login` refresh token, read from the Azure CLI's files (design §4.3.1)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import msal

from ._json import json_object, json_objects
from ._refresh_token import AZURE_CLI_CLIENT_ID, RefreshTokenInfo
from .errors import RefreshTokenNotFoundError, UnsupportedPlatformError

__all__ = ["refresh_token_from_az_cli"]

_PROFILE = "azureProfile.json"
_CACHE = "msal_token_cache.json"
_ENCRYPTED_CACHE = "msal_token_cache.bin"

# The sign-in hosts of the Azure CLI's built-in clouds (`az cloud list`,
# `endpoints.activeDirectory`), with the aliases Entra's instance discovery
# lists for each: a cache entry's `environment` is one of these.
_CLOUD_HOSTS: dict[str, frozenset[str]] = {
    "azurecloud": frozenset(
        {"login.microsoftonline.com", "login.windows.net", "login.microsoft.com", "sts.windows.net"}
    ),
    "azurechinacloud": frozenset({"login.chinacloudapi.cn", "login.partner.microsoftonline.cn"}),
    "azureusgovernment": frozenset({"login.microsoftonline.us", "login.usgovcloudapi.net"}),
    "azuregermancloud": frozenset({"login.microsoftonline.de"}),
}


def _is_windows() -> bool:
    return sys.platform == "win32"


def _config_dir(config_dir: str | os.PathLike[str] | None) -> Path:
    if config_dir is not None:
        return Path(config_dir).expanduser()
    from_env = os.environ.get("AZURE_CONFIG_DIR")
    if from_env:
        return Path(from_env).expanduser()
    return Path.home() / ".azure"


def _read_json(path: Path, encoding: str) -> Any:
    try:
        return json.loads(path.read_text(encoding=encoding))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        # The exception text is not kept: a JSON error can quote the file's content.
        raise RefreshTokenNotFoundError(
            f"{path} could not be read ({type(e).__name__}); run `az login` again."
        ) from None


def _current_account(
    config_dir: Path, username: str | None, tenant_id: str | None
) -> tuple[str, str, str | None]:
    """The (username, tenant, cloud) the Azure CLI is signed in as, with overrides applied.

    The cloud is the subscription's `environmentName` (`AzureCloud`, ...), or
    None when the profile is not read or does not name one.
    """
    if username is not None and tenant_id is not None:
        return username, tenant_id, None
    path = config_dir / _PROFILE
    if not path.is_file():
        raise RefreshTokenNotFoundError(f"No Azure CLI profile at {path}: run `az login`.")
    # The Azure CLI writes this file with a UTF-8 byte order mark.
    profile = json_object(_read_json(path, "utf-8-sig")) or {}
    subscriptions = json_objects(profile.get("subscriptions"))

    def user_of(s: dict[str, Any]) -> str | None:
        user = json_object(s.get("user"))
        name = user.get("name") if user is not None else None
        return name if isinstance(name, str) else None

    def tenant_of(s: dict[str, Any]) -> str | None:
        tenant = s.get("tenantId")
        return tenant if isinstance(tenant, str) and tenant else None

    def cloud_of(s: dict[str, Any]) -> str | None:
        cloud = s.get("environmentName")
        return cloud if isinstance(cloud, str) and cloud else None

    if username is None:
        default = next((s for s in subscriptions if s.get("isDefault") is True), None)
        user = user_of(default) if default is not None else None
        tenant = tenant_of(default) if default is not None else None
        if default is None or not user or tenant is None:
            raise RefreshTokenNotFoundError(f"No default subscription in {path}: run `az login`.")
        return user, tenant_id or tenant, cloud_of(default)

    # Prefer the default subscription when it is the given user's, else any of theirs.
    wanted = username.lower()
    theirs = sorted(
        (s for s in subscriptions if (user_of(s) or "").lower() == wanted and tenant_of(s)),
        key=lambda s: s.get("isDefault") is not True,
    )
    tenant = tenant_of(theirs[0]) if theirs else None
    if tenant is None:
        raise RefreshTokenNotFoundError(
            f"No subscription of {username!r} in {path}: run `az login`, or pass tenant_id."
        )
    return username, tenant, cloud_of(theirs[0])


def _find_refresh_token(config_dir: Path, username: str, tenant: str, cloud: str | None) -> str:
    path = config_dir / _CACHE
    if not path.is_file():
        if (config_dir / _ENCRYPTED_CACHE).is_file():
            raise RefreshTokenNotFoundError(
                f"The Azure CLI token cache is encrypted ({config_dir / _ENCRYPTED_CACHE}), "
                "which dazapiz does not read. Run `az config set core.encrypt_token_cache=false` "
                f"and `az login` again to look up {username!r}, or set $AZURE_REFRESH_TOKEN."
            )
        raise RefreshTokenNotFoundError(
            f"No Azure CLI token cache at {path} for {username!r}: run `az login`."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RefreshTokenNotFoundError(
            f"{path} could not be read ({type(e).__name__}); run `az login` again."
        ) from None
    cache = msal.SerializableTokenCache()
    try:
        cache.deserialize(text)
    except ValueError:
        raise RefreshTokenNotFoundError(
            f"{path} could not be read (not JSON); run `az login` again."
        ) from None

    wanted = username.lower()
    candidates = [
        a
        for a in cache.search(cache.CredentialType.ACCOUNT)
        if (a.get("username") or "").lower() == wanted
    ]
    # One username can be several accounts: one per cloud, or two home
    # accounts. Prefer those in the profile's cloud, then those signed in to
    # the profile's tenant (msal writes one Account entry per tenant, its
    # `realm`). A preference nothing meets is dropped, so a tenant the CLI
    # never signed in to (tenant_id=...) still finds the user's token.
    hosts = _CLOUD_HOSTS.get(cloud.lower()) if cloud is not None else None
    if hosts is not None:
        in_cloud = [a for a in candidates if (a.get("environment") or "").lower() in hosts]
        candidates = in_cloud or candidates
    in_tenant = [a for a in candidates if (a.get("realm") or "").lower() == tenant.lower()]
    accounts = {(a.get("home_account_id"), a.get("environment")) for a in (in_tenant or candidates)}
    tokens = [
        rt
        for rt in cache.search(
            cache.CredentialType.REFRESH_TOKEN, query={"client_id": AZURE_CLI_CLIENT_ID}
        )
        if (rt.get("home_account_id"), rt.get("environment")) in accounts and rt.get("secret")
    ]
    if not tokens:
        raise RefreshTokenNotFoundError(
            f"No Azure CLI refresh token for {username!r} in {path}: run `az login`."
        )
    newest = max(tokens, key=lambda rt: int(rt.get("last_modification_time") or 0))
    secret: str = newest["secret"]
    return secret


def refresh_token_from_az_cli(
    *,
    username: str | None = None,
    tenant_id: str | None = None,
    config_dir: str | os.PathLike[str] | None = None,
) -> RefreshTokenInfo:
    """The refresh token of the account the Azure CLI is signed in as.

    Reads the Azure CLI's files without running `az`, so it also works where
    only the config directory is present (a mounted `~/.azure`):

    1. The config directory is `config_dir`, else `$AZURE_CONFIG_DIR`, else `~/.azure`.
    2. `azureProfile.json` gives the current account: the default subscription's
       user and tenant. `username` and `tenant_id` override them; with both
       given the profile is not read.
    3. `msal_token_cache.json` is loaded into `msal.SerializableTokenCache`, which
       is only read, never written. The refresh token is the newest one issued
       to `AZURE_CLI_CLIENT_ID` for that user's `home_account_id`. Refresh tokens
       carry no tenant, so the tenant comes from the profile.
    4. When the username is several cache accounts (the same name in two
       clouds, or two home accounts), the one in the subscription's cloud
       (`environmentName`) and signed in to its tenant is taken. Where the
       profile cannot tell them apart (both overrides given, a custom cloud,
       a tenant none of them signed in to), the newest token wins.

    An encrypted cache (`msal_token_cache.bin`, from
    `az config set core.encrypt_token_cache=true`) is not read.

    Parameters
    ----------
    username
        The account to look up, matched case-insensitively; default the
        default subscription's user.
    tenant_id
        The tenant the token is for; default the default subscription's
        tenant, or, with `username`, that user's default (else first)
        subscription's tenant.
    config_dir
        The Azure CLI's config directory; default `$AZURE_CONFIG_DIR`, else
        `~/.azure`. `~` is expanded.

    Returns
    -------
    RefreshTokenInfo
        The token, `AZURE_CLI_CLIENT_ID`, the tenant and the username. Pass it
        to `spark_storage_conf(refresh_token=...)` or `RefreshTokenCredential`.

    Raises
    ------
    RefreshTokenNotFoundError
        No profile, no default subscription, no cache or no matching token.
        The message names the file and the username, never a token.
    UnsupportedPlatformError
        On Windows, where the Azure CLI signs in through the Windows broker
        and encrypts its cache.

    Notes
    -----
    Uses `msal.SerializableTokenCache` to read and search the cache; the
    lookup (which file, which entry) is what dazapiz adds. Nothing is
    redeemed here: the token is returned as found, and may have expired if
    the CLI has not been used for a long time (run `az login` again).

    Examples
    --------
    ```python
    from dazapiz import refresh_token_from_az_cli

    info = refresh_token_from_az_cli()
    info.username, info.tenant_id
    ```
    """
    if _is_windows():
        raise UnsupportedPlatformError(
            "refresh_token_from_az_cli() is not available on Windows, where the Azure CLI "
            "keeps its tokens in the Windows broker. Use dazapiz.DeviceCodeCredential or "
            "dazapiz.InteractiveBrowserCredential, or set $AZURE_REFRESH_TOKEN."
        )
    directory = _config_dir(config_dir)
    username, tenant, cloud = _current_account(directory, username, tenant_id)
    token = _find_refresh_token(directory, username, tenant, cloud)
    return RefreshTokenInfo(
        token=token, client_id=AZURE_CLI_CLIENT_ID, tenant_id=tenant, username=username
    )
