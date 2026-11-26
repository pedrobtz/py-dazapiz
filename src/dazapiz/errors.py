"""Errors raised by dazapiz.

Every error derives from `DazapizError`. `azure.core.exceptions.ClientAuthenticationError`
from a credential passes through unwrapped (design §5). No message carries a
token, key or secret (design §6).
"""

from __future__ import annotations

import httpx

__all__ = [
    "ApiError",
    "AzCliError",
    "AzCliNonInteractiveError",
    "AzCliNotFoundError",
    "AzCliNotLoggedInError",
    "AzCliTimeoutError",
    "DazapizError",
    "RefreshTokenNotFoundError",
    "ResponseParseError",
    "UnsupportedPlatformError",
]


class DazapizError(Exception):
    """Base class of every error dazapiz raises.

    Catch it to handle any dazapiz failure. Errors from the Azure SDK itself,
    such as `azure.core.exceptions.ClientAuthenticationError` from a
    credential, are not wrapped and do not derive from it.

    Examples
    --------
    ```python
    from dazapiz import DazapizError, refresh_token_from_az_cli

    try:
        info = refresh_token_from_az_cli()
    except DazapizError as err:
        print(f"No az login token: {err}")
    ```
    """


class RefreshTokenNotFoundError(DazapizError):
    """No refresh token was found where one was looked for.

    Raised by `refresh_token_from_az_cli()` (no profile, no default
    subscription, no token cache or no matching token), by the interactive
    credentials' `get_refresh_token()` (nothing in the persisted cache), and
    wherever a refresh token defaults to `$AZURE_REFRESH_TOKEN` and that is
    unset. The message names the file and the username looked for, never a
    token.
    """


class UnsupportedPlatformError(DazapizError):
    """The operation is not available on this operating system.

    `refresh_token_from_az_cli()` raises it on Windows, where the Azure CLI
    keeps its tokens in the Windows broker.
    """


class AzCliError(DazapizError):
    """An `az` command failed; the message carries what `az` wrote to stderr.

    The base class of the `az` CLI helpers' errors: `az_account_show()`,
    `az_login()` and `az_logout()` raise it, or one of its subclasses.
    """


class AzCliNotFoundError(AzCliError):
    """No `az` on PATH.

    The message links the Azure CLI's installation instructions.
    """


class AzCliNotLoggedInError(AzCliError):
    """The Azure CLI is not logged in.

    Log in with `az_login()`, or `az login` in a terminal.
    """


class AzCliNonInteractiveError(AzCliError):
    """`az_login()` was called where nobody can answer the device-code prompt.

    A session is interactive when standard input is a TTY or a notebook
    kernel is running; a batch job, a pipe or a scheduled run is not.
    """


class AzCliTimeoutError(AzCliError, TimeoutError):
    """An `az` command did not finish within its timeout and was killed.

    Also a `TimeoutError`. The whole process tree `az` started is killed.
    """


class ApiError(DazapizError, httpx.HTTPStatusError):
    """An `ApiClient` request ended in a non-2xx response, after any retries.

    Also an `httpx.HTTPStatusError`, so code written for `httpx` catches it.
    The message carries the method, URL, status and response body, never a
    request header. `request` and `response` are the `httpx` objects.

    Examples
    --------
    ```python
    try:
        client.fetch("/items/{item_id}", item_id="42")
    except ApiError as err:
        if err.response.status_code != 404:
            raise
    ```
    """


class ResponseParseError(DazapizError):
    """A successful response's body could not be parsed or was rejected by `parse=`.

    `ApiClient.fetch()` raises it when its `parse` callable raises on a 2xx
    response's body, and when a body whose content type says JSON or XML
    does not parse. It is not an `ApiError`: the request itself succeeded.

    The message names the method, the URL and the exception's type, never the
    body or a header: a validation error can quote the body. The original
    exception (such as pydantic's `ValidationError`) is `__cause__`.

    Parameters
    ----------
    message
        The error message.
    request
        The request that was sent.
    response
        The successful response whose body failed.

    Attributes
    ----------
    request : httpx.Request
        The request that was sent.
    response : httpx.Response
        The response whose body failed.
    """

    def __init__(self, message: str, *, request: httpx.Request, response: httpx.Response) -> None:
        super().__init__(message)
        self.request = request
        self.response = response
