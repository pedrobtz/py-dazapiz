"""The refresh-token interface (design §4.3, §4.3.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from .errors import RefreshTokenNotFoundError

__all__ = ["AZURE_CLI_CLIENT_ID", "RefreshTokenInfo", "SupportsRefreshToken"]

AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
"""The Azure CLI's public client ID, to which `az login` refresh tokens are issued.

A refresh token can only be redeemed by the client it was issued to, so an
`az login` token is redeemed with this ID. It is also the default client ID
for a refresh token given as a plain string when `$AZURE_CLIENT_ID` is unset.
"""

_REDACTED = "<redacted>"


@dataclass(frozen=True)
class RefreshTokenInfo:
    """A refresh token with the client ID and tenant it belongs to.

    What `refresh_token_from_az_cli()` and every credential's
    `get_refresh_token()` return, and what `spark_storage_conf()` and
    `RefreshTokenCredential` take. It is itself a `SupportsRefreshToken`.
    Frozen; `repr()` and `str()` never show `token`.

    Parameters
    ----------
    token
        The refresh token. A secret.
    client_id
        The client (application) ID the token was issued to, which must
        redeem it.
    tenant_id
        The tenant to redeem it in: a GUID, a domain, `"organizations"` or
        `"common"`.
    username
        The signed-in user, when known.

    Raises
    ------
    TypeError
        A field is not a string (`username` may be `None`).
    ValueError
        `token`, `client_id` or `tenant_id` is empty.

    Examples
    --------
    ```python
    from dazapiz import AZURE_CLI_CLIENT_ID, RefreshTokenInfo

    info = RefreshTokenInfo(token=token, client_id=AZURE_CLI_CLIENT_ID, tenant_id="contoso.com")
    info  # RefreshTokenInfo(token='<redacted>', client_id='04b07795-...', ...)
    ```
    """

    token: str
    client_id: str
    tenant_id: str
    username: str | None = None

    def __post_init__(self) -> None:
        """Check the fields' types and that the required ones are not empty."""
        for name in ("token", "client_id", "tenant_id"):
            value: object = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"RefreshTokenInfo.{name} must be a str, not {type(value).__name__}"
                )
            if not value:
                raise ValueError(f"RefreshTokenInfo.{name} must not be empty")
        username = cast(object, self.username)  # checked at run time: callers may be untyped
        if username is not None and not isinstance(username, str):
            raise TypeError("RefreshTokenInfo.username must be a str or None")

    def __repr__(self) -> str:
        """The fields with the token shown as `<redacted>`."""
        return (
            f"RefreshTokenInfo(token={_REDACTED!r}, client_id={self.client_id!r}, "
            f"tenant_id={self.tenant_id!r}, username={self.username!r})"
        )

    def get_refresh_token(self) -> RefreshTokenInfo:
        """Return itself, so a `RefreshTokenInfo` is a `SupportsRefreshToken`.

        Returns
        -------
        RefreshTokenInfo
            This object.
        """
        return self


@runtime_checkable
class SupportsRefreshToken(Protocol):
    """Anything that can hand over a refresh token with its client ID and tenant.

    A runtime-checkable protocol with one method, `get_refresh_token()`,
    returning a `RefreshTokenInfo`. `RefreshTokenInfo` itself,
    `RefreshTokenCredential`, `DeviceCodeCredential` and
    `InteractiveBrowserCredential` implement it; `spark_storage_conf()` and
    `RefreshTokenCredential` accept any of them where a refresh token is
    expected. `azure-identity` credentials do not: they keep refresh tokens
    private.

    Examples
    --------
    ```python
    from dazapiz import RefreshTokenInfo, SupportsRefreshToken

    class FromVault:
        def get_refresh_token(self) -> RefreshTokenInfo:
            return RefreshTokenInfo(token=read_secret(), client_id=CLIENT, tenant_id=TENANT)

    isinstance(FromVault(), SupportsRefreshToken)  # True
    ```
    """

    def get_refresh_token(self) -> RefreshTokenInfo:
        """Return the refresh token with its client ID and tenant.

        Returns
        -------
        RefreshTokenInfo
            The token and what it belongs to.
        """
        ...


def env(name: str) -> str | None:
    # An empty variable counts as unset; azr passes "" on (design §4.3.4).
    return os.environ.get(name) or None


def as_refresh_token_info(refresh_token: str | SupportsRefreshToken | None) -> RefreshTokenInfo:
    """Coerce a refresh token argument with the design §4.3.4 defaults.

    - `None`: `$AZURE_REFRESH_TOKEN`, else `RefreshTokenNotFoundError`.
    - A string (given or from the variable): client ID `$AZURE_CLIENT_ID`, else
      `AZURE_CLI_CLIENT_ID`; tenant `$AZURE_TENANT_ID`, else `"common"`.
    - A `SupportsRefreshToken`: its own `get_refresh_token()`, untouched.

    Nothing here reads a cache or the disk (design D17).
    """
    if refresh_token is None:
        refresh_token = env("AZURE_REFRESH_TOKEN")
        if refresh_token is None:
            raise RefreshTokenNotFoundError(
                "No refresh token: pass one, or a credential such as "
                "refresh_token_from_az_cli(), or set $AZURE_REFRESH_TOKEN."
            )
    if isinstance(refresh_token, str):
        if not refresh_token:
            raise ValueError("refresh_token must not be empty")
        return RefreshTokenInfo(
            token=refresh_token,
            client_id=env("AZURE_CLIENT_ID") or AZURE_CLI_CLIENT_ID,
            tenant_id=env("AZURE_TENANT_ID") or "common",
        )
    given = cast(object, refresh_token)  # checked at run time: callers may be untyped
    if isinstance(given, SupportsRefreshToken):
        # A runtime-checkable protocol checks the method's name only, not what it returns.
        info = cast(object, given.get_refresh_token())
        if not isinstance(info, RefreshTokenInfo):
            raise TypeError(
                f"{type(given).__name__}.get_refresh_token() returned "
                f"{type(info).__name__}, not RefreshTokenInfo"
            )
        return info
    raise TypeError(
        f"refresh_token must be a str, a SupportsRefreshToken or None, not {type(given).__name__}"
    )
