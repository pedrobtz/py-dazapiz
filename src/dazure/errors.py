"""Errors raised by dazure.

Every error derives from `DazureError`. `azure.core.exceptions.ClientAuthenticationError`
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
    "DazureError",
    "RefreshTokenNotFoundError",
    "UnsupportedPlatformError",
]


class DazureError(Exception):
    """Base class of every error dazure raises."""


class RefreshTokenNotFoundError(DazureError):
    """No refresh token was found where one was looked for.

    The message names the file and the username looked for, never a token.
    """


class UnsupportedPlatformError(DazureError):
    """The operation is not available on this operating system."""


class AzCliError(DazureError):
    """An `az` command failed; the message carries what `az` wrote to stderr."""


class AzCliNotFoundError(AzCliError):
    """No `az` on PATH."""


class AzCliNotLoggedInError(AzCliError):
    """The Azure CLI is not logged in."""


class AzCliNonInteractiveError(AzCliError):
    """`az_login()` was called where nobody can answer the device-code prompt."""


class AzCliTimeoutError(AzCliError, TimeoutError):
    """An `az` command did not finish within its timeout and was killed."""


class ApiError(DazureError, httpx.HTTPStatusError):
    """An `ApiClient` request ended in a non-2xx response, after any retries.

    The message carries the method, URL, status and response body, never a
    request header. `request` and `response` are the `httpx` objects.
    """
