"""Interactive credentials that hand over their refresh token (design §4.3.2, §4.3.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import azure.identity
import msal
from azure.identity import AuthenticationRecord, TokenCachePersistenceOptions

from ._pasted_code import is_localhost, request_token_by_pasted_code
from ._refresh_token import RefreshTokenInfo
from .errors import RefreshTokenNotFoundError

__all__ = ["DeviceCodeCredential", "InteractiveBrowserCredential", "find_refresh_token"]

CACHE_NAME = "dazure"

# azure-identity's `_load_persistent_cache()` passes this account name to
# `_get_persistence()`; the cache file suffixes are its `_constants`.
_ACCOUNT_NAME = "MSALCache"
_SUFFIXES = (".nocae", ".cae")


def _cache_options(kwargs: dict[str, Any], allow_unencrypted_storage: bool) -> None:
    options = kwargs.get("cache_persistence_options")
    if options is None:
        kwargs["cache_persistence_options"] = TokenCachePersistenceOptions(
            name=CACHE_NAME, allow_unencrypted_storage=allow_unencrypted_storage
        )
    elif allow_unencrypted_storage:
        raise ValueError(
            "Pass allow_unencrypted_storage in your cache_persistence_options, not both."
        )


def find_refresh_token(
    options: TokenCachePersistenceOptions, record: AuthenticationRecord
) -> RefreshTokenInfo:
    """Read the refresh token of `record` from the persisted cache of `options`.

    Opens the same `msal_extensions` persistences azure-identity opens for
    `options` (its private `_persistent_cache._get_persistence()`), `.nocae` and
    `.cae`, and only loads them: nothing is written or copied (design §6).
    """
    import msal_extensions

    # Private azure-identity API (D16); the layout guard is the manual check of §8.2.
    from azure.identity import _persistent_cache  # pyright: ignore[reportPrivateUsage]

    tokens: list[dict[str, Any]] = []
    for suffix in _SUFFIXES:
        persistence = _persistent_cache._get_persistence(  # pyright: ignore[reportPrivateUsage]
            allow_unencrypted=options.allow_unencrypted_storage,
            account_name=_ACCOUNT_NAME,
            cache_name=options.name + suffix,
        )
        try:
            text = persistence.load()
        except msal_extensions.persistence.PersistenceNotFound:
            continue
        if not text:
            continue
        cache = msal.SerializableTokenCache()
        try:
            cache.deserialize(text)
        except ValueError:
            raise RefreshTokenNotFoundError(
                f"The {options.name!r} token cache could not be read (not JSON); "
                "sign in again with authenticate()."
            ) from None
        tokens += [
            rt
            for rt in cache.search(
                cache.CredentialType.REFRESH_TOKEN,
                query={"home_account_id": record.home_account_id, "client_id": record.client_id},
            )
            if rt.get("secret")
        ]
    if not tokens:
        raise RefreshTokenNotFoundError(
            f"No refresh token for {record.username!r} (client {record.client_id}) in the "
            f"{options.name!r} token cache: sign in again with authenticate()."
        )
    newest = max(tokens, key=lambda rt: int(rt.get("last_modification_time") or 0))
    return RefreshTokenInfo(
        token=newest["secret"],
        client_id=record.client_id,
        tenant_id=record.tenant_id,
        username=record.username,
    )


class _RefreshTokenFromCache:
    # Declared, not defined: the azure-identity parent provides them.
    _auth_record: AuthenticationRecord | None
    _cache_options: TokenCachePersistenceOptions
    authenticate: Callable[..., AuthenticationRecord]

    def get_refresh_token(self) -> RefreshTokenInfo:
        """The signed-in user's refresh token, signing in first if nobody has.

        Calls `authenticate()` when the credential has no `AuthenticationRecord`
        yet, then reads the token from the persisted cache azure-identity wrote,
        with the record's client ID, tenant and username.

        Returns
        -------
        RefreshTokenInfo
            The newest refresh token in the cache for the signed-in account.

        Raises
        ------
        RefreshTokenNotFoundError
            The persisted cache holds no refresh token for the account, or
            cannot be read.

        Notes
        -----
        The cache is opened with the same `msal_extensions` persistence
        `azure-identity` uses for its `cache_persistence_options`, and only
        loaded: nothing is written or copied. This reads azure-identity's
        private `_persistent_cache` layout, which its public API does not
        expose.
        """
        record = self._auth_record or self.authenticate()
        return find_refresh_token(self._cache_options, record)


class DeviceCodeCredential(_RefreshTokenFromCache, azure.identity.DeviceCodeCredential):
    """`azure.identity.DeviceCodeCredential` with a persisted cache and `get_refresh_token()`.

    Signs in with a device code: it prints a URL and a code, and the user
    signs in from any browser, on any machine. Use it where no browser can
    reach the machine running Python. As a `SupportsRefreshToken`, it can be
    passed to `spark_storage_conf(refresh_token=...)`.

    Parameters
    ----------
    *args
        Passed to `azure.identity.DeviceCodeCredential` (`client_id`, which
        defaults to the Azure CLI's).
    allow_unencrypted_storage
        Fall back to a plain file where the platform's secret store is
        unusable (a headless Linux machine). Pass it inside your own
        `cache_persistence_options` instead when you give those.
    **kwargs
        Passed to `azure.identity.DeviceCodeCredential`: `tenant_id`,
        `authority`, `timeout`, `prompt_callback`, `authentication_record`
        and the rest.

    Raises
    ------
    ValueError
        `allow_unencrypted_storage=True` together with
        `cache_persistence_options`.

    Notes
    -----
    Everything but the cache default and `get_refresh_token()` is
    `azure-identity`'s. Tokens are cached in the platform store under the
    name `"dazure"` unless `cache_persistence_options` is given, so a later
    session with the same `authentication_record` signs in silently.

    Examples
    --------
    ```python
    from dazure import DeviceCodeCredential, spark_storage_conf

    credential = DeviceCodeCredential(tenant_id="contoso.com")
    conf = spark_storage_conf(refresh_token=credential)  # prompts once
    ```
    """

    def __init__(self, *args: Any, allow_unencrypted_storage: bool = False, **kwargs: Any) -> None:
        _cache_options(kwargs, allow_unencrypted_storage)
        super().__init__(*args, **kwargs)


class InteractiveBrowserCredential(
    _RefreshTokenFromCache, azure.identity.InteractiveBrowserCredential
):
    """`azure.identity.InteractiveBrowserCredential` with a persisted cache and `get_refresh_token()`.

    It also signs in through a callback page, as httr2 does. With no `redirect_uri` or a localhost one, the parent's local listener and
    system browser sign in. Any other `redirect_uri` (a page the user's browser
    can load, such as a code-server URL) prints MSAL's authorize URL and reads
    back what the callback page shows: the callback URL, base64 JSON with `code`
    and `state`, or the code and then the state, as `httr2::req_oauth_auth_code()`
    does. That needs an interactive session. Caching is as `DeviceCodeCredential`.

    Parameters
    ----------
    allow_unencrypted_storage
        Fall back to a plain file where the platform's secret store is
        unusable, as for `DeviceCodeCredential`.
    **kwargs
        Passed to `azure.identity.InteractiveBrowserCredential`: `tenant_id`,
        `client_id`, `redirect_uri`, `login_hint`, `authority`,
        `authentication_record` and the rest. A `redirect_uri` whose host is
        not `localhost` or `127.0.0.1` is kept by dazure for the pasted-code
        flow and not passed on.

    Raises
    ------
    ValueError
        `allow_unencrypted_storage=True` together with
        `cache_persistence_options`, or (from the parent) a localhost
        `redirect_uri` without a port.

    Notes
    -----
    Everything but the cache default, `get_refresh_token()` and the
    pasted-code flow is `azure-identity`'s. The pasted-code flow uses the
    parent's MSAL app: `initiate_auth_code_flow()` builds the PKCE pair,
    state and nonce, and `acquire_token_by_auth_code_flow()` checks the state
    and redeems the code, so the tokens land in the same cache. Signing in
    raises `azure.identity.CredentialUnavailableError` in a session that is
    not interactive (no TTY, no notebook kernel), and
    `azure.core.exceptions.ClientAuthenticationError` for a pasted reply with
    an error, no code, no state, or a state that does not match. The app
    registration must list the redirect URI as a public client ("Mobile and
    desktop applications"), since no client secret is sent.

    Examples
    --------
    ```python
    from dazure import InteractiveBrowserCredential

    credential = InteractiveBrowserCredential(
        tenant_id="11111111-2222-3333-4444-555555555555",
        client_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        redirect_uri="https://your-domain.example/azure-callback",
    )
    token = credential.get_token("User.Read").token  # prompts once, then silent
    ```
    """

    def __init__(self, *, allow_unencrypted_storage: bool = False, **kwargs: Any) -> None:
        redirect_uri = kwargs.get("redirect_uri")
        self._pasted_redirect_uri: str | None = None
        if redirect_uri and not is_localhost(redirect_uri):
            # Kept here: the parent would demand a port and listen on its host.
            self._pasted_redirect_uri = kwargs.pop("redirect_uri")
        _cache_options(kwargs, allow_unencrypted_storage)
        super().__init__(**kwargs)

    def _request_token(self, *scopes: str, **kwargs: Any) -> dict[str, Any]:
        if self._pasted_redirect_uri is None:
            # azure-identity's private method (D22) is annotated `-> Dict` with untyped kwargs.
            result = super()._request_token(*scopes, **kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            return cast("dict[str, Any]", result)
        return request_token_by_pasted_code(
            self._get_app(**kwargs),
            list(scopes),
            redirect_uri=self._pasted_redirect_uri,
            login_hint=self._login_hint,
            claims=kwargs.get("claims"),
        )
