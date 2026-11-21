"""RefreshTokenCredential (design §4.3.5)."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from typing import Any

import msal
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureAuthorityHosts

from ._refresh_token import RefreshTokenInfo, SupportsRefreshToken, as_refresh_token_info

__all__ = ["RefreshTokenCredential"]

# An access token is renewed when it has this many seconds or fewer left.
_EXPIRY_MARGIN = 300


def _authority_url(authority_host: str | None, tenant_id: str) -> str:
    host = (
        authority_host
        or os.environ.get("AZURE_AUTHORITY_HOST")
        or (AzureAuthorityHosts.AZURE_PUBLIC_CLOUD)
    )
    if "://" not in host:
        host = "https://" + host
    return f"{host.rstrip('/')}/{tenant_id}"


class RefreshTokenCredential:
    """A `TokenCredential` that redeems a refresh token for access tokens.

    Use it wherever the Azure SDK, `ApiClient` or
    `dazure.duckdb.set_credential_secret()` takes a credential, to act as
    the user an `az login` (or any other sign-in) refresh token belongs to.
    Access tokens are kept in memory, per tenant and scope set, until five
    minutes before they expire. When Entra rotates the refresh token, the new
    one is kept and returned by `get_refresh_token()`. Thread-safe.

    Parameters
    ----------
    refresh_token
        A refresh token string, a `SupportsRefreshToken` (such as
        `refresh_token_from_az_cli()`), or `None` for `$AZURE_REFRESH_TOKEN`.
        A string is redeemed with `$AZURE_CLIENT_ID`, else
        `AZURE_CLI_CLIENT_ID`, in `$AZURE_TENANT_ID`, else `"common"`; a
        `SupportsRefreshToken` brings its own client ID and tenant.
    authority_host
        The Entra authority host, with or without `https://`; default
        `$AZURE_AUTHORITY_HOST`, else the public cloud
        (`login.microsoftonline.com`).

    Raises
    ------
    RefreshTokenNotFoundError
        `refresh_token` is `None` and `$AZURE_REFRESH_TOKEN` is unset.
    TypeError
        `refresh_token` is of another type.
    ValueError
        `refresh_token` is an empty string.

    Notes
    -----
    Wraps `msal.PublicClientApplication.acquire_token_by_refresh_token()`,
    one MSAL app per tenant. `azure-identity` has no credential that takes a
    refresh token. `repr()` shows the client ID, tenant and username, never
    a token.

    Examples
    --------
    ```python
    from azure.storage.filedatalake import DataLakeServiceClient
    from dazure import RefreshTokenCredential, refresh_token_from_az_cli

    credential = RefreshTokenCredential(refresh_token_from_az_cli())
    lake = DataLakeServiceClient("https://myaccount.dfs.core.windows.net", credential)
    ```
    """

    def __init__(
        self,
        refresh_token: str | SupportsRefreshToken | None = None,
        *,
        authority_host: str | None = None,
    ) -> None:
        self._info = as_refresh_token_info(refresh_token)
        self._authority_host = authority_host
        self._lock = threading.Lock()
        self._apps: dict[str, Any] = {}
        self._tokens: dict[tuple[str, frozenset[str]], AccessToken] = {}

    def __repr__(self) -> str:
        """The client ID, tenant and username; never a token."""
        info = self._info
        return (
            f"RefreshTokenCredential(client_id={info.client_id!r}, "
            f"tenant_id={info.tenant_id!r}, username={info.username!r})"
        )

    def get_refresh_token(self) -> RefreshTokenInfo:
        """The current refresh token: the one given, or the latest rotated one.

        Returns
        -------
        RefreshTokenInfo
            The refresh token with its client ID, tenant and username.
        """
        return self._info

    def _app(self, tenant_id: str) -> Any:
        app = self._apps.get(tenant_id)
        if app is None:
            app = msal.PublicClientApplication(
                self._info.client_id,
                authority=_authority_url(self._authority_host, tenant_id),
            )
            self._apps[tenant_id] = app
        return app

    def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> AccessToken:
        """An access token for `scopes`, from memory or by redeeming the refresh token.

        The `TokenCredential` protocol's method, which the Azure SDK calls.

        Parameters
        ----------
        *scopes
            One or more scopes, such as `"https://storage.azure.com/.default"`.
        claims
            A claims challenge from a resource; skips the in-memory token and
            is sent to Entra.
        tenant_id
            Request the token from this tenant instead of the refresh token's
            own.
        **kwargs
            Accepted for the protocol and ignored.

        Returns
        -------
        azure.core.credentials.AccessToken
            The token and its `expires_on` (seconds since the epoch).

        Raises
        ------
        ValueError
            No scope was given.
        azure.core.exceptions.ClientAuthenticationError
            Entra refused the refresh token (expired, revoked, or for another
            client); the message carries MSAL's error, never the token.
        """
        if not scopes:
            raise ValueError("get_token() requires at least one scope")
        with self._lock:
            tenant = tenant_id or self._info.tenant_id
            key = (tenant, frozenset(scopes))
            cached = self._tokens.get(key)
            fresh = cached is not None and cached.expires_on - time.time() > _EXPIRY_MARGIN
            if claims is None and cached is not None and fresh:
                return cached

            secret = self._info.token
            extra: dict[str, Any] = {"data": {"claims": claims}} if claims else {}
            now = time.time()
            result = self._app(tenant).acquire_token_by_refresh_token(secret, list(scopes), **extra)
            if "access_token" not in result:
                error = result.get("error") or "unknown_error"
                description = result.get("error_description") or ""
                message = f"Refresh token redemption failed: {error}. {description}".strip()
                raise ClientAuthenticationError(message=message.replace(secret, "<redacted>"))

            rotated = result.get("refresh_token")
            if rotated and rotated != secret:
                self._info = replace(self._info, token=rotated)
            token = AccessToken(result["access_token"], int(now) + int(result["expires_in"]))
            self._tokens[key] = token
            return token
