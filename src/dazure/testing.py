"""Test doubles for code built on dazure (design §5, D59).

`StaticTokenCredential` stands in for an Azure credential in tests that run
without Azure, such as an `ApiClient` subclass's tests in CI: pass it as
`credential=` and mock the HTTP with `respx` or `httpx.MockTransport`. The
guide page "Testing your API client" shows the whole pattern.
"""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

from azure.core.credentials import AccessToken, AccessTokenInfo, TokenRequestOptions

__all__ = ["StaticTokenCredential"]


class StaticTokenCredential:
    """A credential that returns a fixed token and records what it was asked for.

    Implements azure-core's `TokenCredential` and `SupportsTokenInfo`
    protocols without signing in or touching the network, so an
    `ApiClient` (or any Azure SDK client) can be tested offline. Each call
    returns a fresh token that expires `expires_in` seconds from now.

    Parameters
    ----------
    token : str
        The access token to hand out; default ``"fake-token"``, so requests
        carry ``Authorization: Bearer fake-token``.
    expires_in : int
        Seconds until each returned token expires; default 3600.

    Attributes
    ----------
    calls : list of tuple of str
        The scopes of each `get_token()` or `get_token_info()` call, in
        order, one tuple per call.

    Notes
    -----
    It wraps nothing: it is a plain object satisfying azure-core's
    `azure.core.credentials.TokenCredential` and `SupportsTokenInfo`
    protocols. `claims`, `tenant_id` and the `options` of `get_token_info()`
    are accepted and ignored. The token is redacted in `repr` (design §6),
    although it is only a test value.

    Examples
    --------
    ```python
    from dazure.testing import StaticTokenCredential

    credential = StaticTokenCredential()
    client = MyApiClient(credential=credential)  # requests send "Bearer fake-token"
    ...
    assert credential.calls == [(MyApiClient.scope,)]
    ```
    """

    def __init__(self, token: str = "fake-token", *, expires_in: int = 3600) -> None:
        self._token = token
        self._expires_in = expires_in
        self.calls: list[tuple[str, ...]] = []

    def __repr__(self) -> str:
        """The expiry and number of calls; never the token."""
        return (
            f"StaticTokenCredential(token=<redacted>, expires_in={self._expires_in}, "
            f"calls={len(self.calls)})"
        )

    def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: Any,
    ) -> AccessToken:
        """Return the fixed token for `scopes`, and record them.

        Parameters
        ----------
        *scopes : str
            The scopes asked for, recorded in `calls`.
        claims : str or None
            Ignored.
        tenant_id : str or None
            Ignored.
        enable_cae : bool
            Ignored.
        **kwargs : Any
            Ignored.

        Returns
        -------
        azure.core.credentials.AccessToken
            The token, expiring `expires_in` seconds from now.
        """
        self.calls.append(scopes)
        return AccessToken(self._token, int(time.time()) + self._expires_in)

    def get_token_info(
        self, *scopes: str, options: TokenRequestOptions | None = None
    ) -> AccessTokenInfo:
        """Return the fixed token for `scopes` as `AccessTokenInfo`, and record them.

        Parameters
        ----------
        *scopes : str
            The scopes asked for, recorded in `calls`.
        options : TokenRequestOptions or None
            Ignored.

        Returns
        -------
        azure.core.credentials.AccessTokenInfo
            The token, of type ``Bearer``, expiring `expires_in` seconds
            from now.
        """
        self.calls.append(scopes)
        return AccessTokenInfo(self._token, int(time.time()) + self._expires_in)

    def close(self) -> None:
        """Do nothing: there is nothing to release."""

    def __enter__(self) -> StaticTokenCredential:
        """Return the credential itself.

        Returns
        -------
        StaticTokenCredential
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Do nothing, as `close()`.

        Parameters
        ----------
        exc_type, exc_value, traceback
            The exception leaving the `with` block, if any.
        """
