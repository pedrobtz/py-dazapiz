"""The Azure helpers azure-identity lacks.

The design is in `.agents/design.md` in the repository.
"""

from importlib.metadata import version

from ._refresh_token import AZURE_CLI_CLIENT_ID, RefreshTokenInfo, SupportsRefreshToken
from .errors import DazureError, RefreshTokenNotFoundError, UnsupportedPlatformError

__version__ = version("dazure")

__all__ = [
    "AZURE_CLI_CLIENT_ID",
    "DazureError",
    "RefreshTokenInfo",
    "RefreshTokenNotFoundError",
    "SupportsRefreshToken",
    "UnsupportedPlatformError",
    "__version__",
]
