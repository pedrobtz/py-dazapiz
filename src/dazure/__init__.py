"""The Azure helpers azure-identity lacks.

Your `az login` carried into Spark (`spark_storage_conf()`), DuckDB
(`dazure.duckdb`) and any Azure REST API (`ApiClient`), on top of
`azure-identity` and `msal`. The design is in `.agents/design.md` in the
repository.
"""

from importlib.metadata import version

from ._api_client import ApiClient
from ._app_credential import app_credential
from ._az import az_account_show, az_is_login, az_login, az_logout
from ._az_cli_token import refresh_token_from_az_cli
from ._credential import RefreshTokenCredential
from ._interactive import DeviceCodeCredential, InteractiveBrowserCredential
from ._refresh_token import AZURE_CLI_CLIENT_ID, RefreshTokenInfo, SupportsRefreshToken
from ._spark_conf import SparkStorageConf, spark_storage_conf
from .errors import (
    ApiError,
    AzCliError,
    AzCliNonInteractiveError,
    AzCliNotFoundError,
    AzCliNotLoggedInError,
    AzCliTimeoutError,
    DazureError,
    RefreshTokenNotFoundError,
    ResponseParseError,
    UnsupportedPlatformError,
)

__version__ = version("dazure")
"""The installed version of dazure, from the package metadata."""

__all__ = [
    "AZURE_CLI_CLIENT_ID",
    "ApiClient",
    "ApiError",
    "AzCliError",
    "AzCliNonInteractiveError",
    "AzCliNotFoundError",
    "AzCliNotLoggedInError",
    "AzCliTimeoutError",
    "DazureError",
    "DeviceCodeCredential",
    "InteractiveBrowserCredential",
    "RefreshTokenCredential",
    "RefreshTokenInfo",
    "RefreshTokenNotFoundError",
    "ResponseParseError",
    "SparkStorageConf",
    "SupportsRefreshToken",
    "UnsupportedPlatformError",
    "__version__",
    "app_credential",
    "az_account_show",
    "az_is_login",
    "az_login",
    "az_logout",
    "refresh_token_from_az_cli",
    "spark_storage_conf",
]
