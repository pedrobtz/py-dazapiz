# Changelog

## 0.1.0 (unreleased)

- `refresh_token_from_az_cli()` returns the refresh token of the account
  the Azure CLI is signed in as, read from `azureProfile.json` and
  `msal_token_cache.json` without running `az` (macOS and Linux; Windows
  raises `UnsupportedPlatformError`).
- `RefreshTokenCredential` redeems a refresh token for access tokens as a
  `TokenCredential`, caching them until five minutes before expiry and
  keeping the rotated refresh token.
- `RefreshTokenInfo`, `SupportsRefreshToken` and `AZURE_CLI_CLIENT_ID`: a
  refresh token always travels with its client ID and tenant; a plain
  string or `$AZURE_REFRESH_TOKEN` takes `$AZURE_CLIENT_ID` (else the CLI's
  client ID) and `$AZURE_TENANT_ID` (else `"common"`).
- `dazure.errors`: `DazureError`, `RefreshTokenNotFoundError`,
  `UnsupportedPlatformError`. No token appears in a `repr`, `str` or error
  message.
