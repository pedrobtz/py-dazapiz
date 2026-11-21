"""Errors raised by dazure.

Every error derives from `DazureError`. `azure.core.exceptions.ClientAuthenticationError`
from a credential passes through unwrapped (design §5). No message carries a
token, key or secret (design §6).
"""

from __future__ import annotations

__all__ = ["DazureError", "RefreshTokenNotFoundError", "UnsupportedPlatformError"]


class DazureError(Exception):
    """Base class of every error dazure raises."""


class RefreshTokenNotFoundError(DazureError):
    """No refresh token was found where one was looked for.

    The message names the file and the username looked for, never a token.
    """


class UnsupportedPlatformError(DazureError):
    """The operation is not available on this operating system."""
