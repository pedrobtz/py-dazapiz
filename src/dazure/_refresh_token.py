"""The refresh-token interface (design §4.3, §4.3.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .errors import RefreshTokenNotFoundError

__all__ = ["AZURE_CLI_CLIENT_ID", "RefreshTokenInfo", "SupportsRefreshToken"]

#: The Azure CLI's public client ID, to which `az login` refresh tokens are issued.
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

_REDACTED = "<redacted>"


@dataclass(frozen=True)
class RefreshTokenInfo:
    """A refresh token with the client ID and tenant it belongs to.

    `repr()` and `str()` never show `token`.
    """

    token: str
    client_id: str
    tenant_id: str
    username: str | None = None

    def __post_init__(self) -> None:
        for name in ("token", "client_id", "tenant_id"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"RefreshTokenInfo.{name} must be a str, not {type(value).__name__}"
                )
            if not value:
                raise ValueError(f"RefreshTokenInfo.{name} must not be empty")
        if self.username is not None and not isinstance(self.username, str):
            raise TypeError("RefreshTokenInfo.username must be a str or None")

    def __repr__(self) -> str:
        return (
            f"RefreshTokenInfo(token={_REDACTED!r}, client_id={self.client_id!r}, "
            f"tenant_id={self.tenant_id!r}, username={self.username!r})"
        )

    def get_refresh_token(self) -> RefreshTokenInfo:
        """Return itself, so a `RefreshTokenInfo` is a `SupportsRefreshToken`."""
        return self


@runtime_checkable
class SupportsRefreshToken(Protocol):
    """Anything that can hand over a refresh token with its client ID and tenant."""

    def get_refresh_token(self) -> RefreshTokenInfo: ...


def _env(name: str) -> str | None:
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
        refresh_token = _env("AZURE_REFRESH_TOKEN")
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
            client_id=_env("AZURE_CLIENT_ID") or AZURE_CLI_CLIENT_ID,
            tenant_id=_env("AZURE_TENANT_ID") or "common",
        )
    if isinstance(refresh_token, SupportsRefreshToken):
        info = refresh_token.get_refresh_token()
        if not isinstance(info, RefreshTokenInfo):
            raise TypeError(
                f"{type(refresh_token).__name__}.get_refresh_token() returned "
                f"{type(info).__name__}, not RefreshTokenInfo"
            )
        return info
    raise TypeError(
        "refresh_token must be a str, a SupportsRefreshToken or None, "
        f"not {type(refresh_token).__name__}"
    )
