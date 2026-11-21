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
- `spark_storage_conf()` builds the Hadoop `fs.azure.*` keys for Spark
  to read ADLS Gen2 with a refresh token, a service principal, workload
  or managed identity, or an account key, key for key as
  `azr::azure_spark_storage_conf()` when arguments are explicit. Its
  defaults differ from `azr`'s: a service principal or workload identity
  needs `$AZURE_CLIENT_ID` and `$AZURE_TENANT_ID` rather than falling back
  to the CLI client ID, and managed identity without a client ID is the
  system-assigned identity. It returns a `SparkStorageConf`, a
  `dict[str, str]` whose `repr` and `str` redact the secret, refresh token
  and account key.
- `dazure.errors`: `DazureError`, `RefreshTokenNotFoundError`,
  `UnsupportedPlatformError`. No token appears in a `repr`, `str` or error
  message.
