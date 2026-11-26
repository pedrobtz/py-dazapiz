# Changelog

## 0.1.0 (2026-11-26)

The first release. `dazapiz` adds what `azure-identity` lacks: your
`az login` carried into Spark, DuckDB and any Azure REST API. Where
`azure-identity` or `msal` already does a job, `dazapiz` calls it. It needs
Python 3.10 or later.

### Refresh tokens and credentials

- `refresh_token_from_az_cli()` returns the refresh token of the account
  the Azure CLI is signed in as, read from `azureProfile.json` and
  `msal_token_cache.json` without running `az` (macOS and Linux; Windows
  raises `UnsupportedPlatformError`).
- When one username is several accounts in the Azure CLI's cache (the same
  name in two clouds, or two home accounts), `refresh_token_from_az_cli()`
  takes the one in the profile's cloud and tenant, not the newest (#47).
- `RefreshTokenCredential` redeems a refresh token for access tokens as a
  `TokenCredential`, caching them until five minutes before expiry and
  keeping the rotated refresh token.
- `RefreshTokenInfo`, `SupportsRefreshToken` and `AZURE_CLI_CLIENT_ID`: a
  refresh token always travels with its client ID and tenant; a plain
  string or `$AZURE_REFRESH_TOKEN` takes `$AZURE_CLIENT_ID` (else the CLI's
  client ID) and `$AZURE_TENANT_ID` (else `"common"`).
- `DeviceCodeCredential` and `InteractiveBrowserCredential` subclass the
  `azure-identity` classes, keep their token cache in the platform store
  under the name `"dazapiz"` (`allow_unencrypted_storage=True` falls back
  to a plain file), and add `get_refresh_token()`, which signs in if
  needed and returns the refresh token from that cache.
- `InteractiveBrowserCredential` with a redirect URI that is not on
  localhost signs in as `httr2::req_oauth_auth_code()` does: it prints
  the sign-in URL and reads back the callback URL, base64 JSON, or the
  code and state shown by the callback page, so it works from
  code-server and notebooks in the cloud.
- `app_credential()` chooses an API's credential from its own service
  principal variables (`client_id_env`, `client_secret_env`,
  `tenant_id_env`) and the mode (`prod`, `dev`, a single credential
  name, or automatic), from the argument or `$AZURE_TOKEN_CREDENTIALS`;
  a partly set service principal raises `ValueError` naming the missing
  variable. In `dev` mode the device code has no persisted cache, so it
  prompts on headless Linux too (#39). A `$AZURE_TOKEN_CREDENTIALS` value
  that `DefaultAzureCredential` takes but dazapiz does not build
  (`AzureDeveloperCliCredential`, ...) means automatic, with a warning
  (#44).

### Spark

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

### Azure CLI

- `az_account_show()`, `az_is_login()`, `az_login()` and `az_logout()` run
  the `az` found on `PATH`, with `--only-show-errors` and a 10-second
  timeout (none for `az_login()`). `az_login()` reuses an existing login
  (into `tenant_id`, if given) unless `force=True`; otherwise it runs
  `az login --use-device-code`, prints the device code and URL as `az`
  streams them, copies the code to the clipboard when a clipboard tool is
  found, and returns the account. Its `timeout` covers the whole login,
  the `az account show` checks included (#37), and a `tenant_id` domain
  matches the account's default domain (#38). Errors: `AzCliError` and its
  subclasses `AzCliNotFoundError`, `AzCliNotLoggedInError`,
  `AzCliNonInteractiveError` (no TTY or notebook kernel) and
  `AzCliTimeoutError`.

### REST client

- `ApiClient`, a small `httpx` client for one REST API, meant to be
  subclassed: `fetch()` fills `{name}` path placeholders (URL-encoded; a
  conversion or format spec is refused, #45), refuses an absolute URL so
  the bearer token never leaves the client's host (#36), leaves `None`
  query values out (#40), retries 429, 503 and connection failures up to
  `max_tries` with `Retry-After` (an invalid or infinite one falls back,
  #41) or `azr`'s backoff, parses JSON (`application/json`, `text/json`,
  `+json`), XML (`application/xml`, `text/xml`, `+xml`) or text by content
  type (#43), and raises `ApiError` (an `httpx.HTTPStatusError`) with the
  method, URL, status and body. The bearer token is fetched from the
  credential once and renewed five minutes before expiry. Subclasses
  that set `client_id_env` and `client_secret_env` get their credential
  from `app_credential()`; `with SomeApiClient() as client:` types
  `client` as the subclass.
- `fetch(..., parse=f)` returns `f(body)`, typed as `f`'s result, so
  `parse=Model.model_validate` or `TypeAdapter(list[Model]).validate_python`
  validates the body. A body that does not parse, or an exception from
  `f`, raises `ResponseParseError`, which names the method and URL but not
  the body.
- `fetch(json=...)` sends a pydantic model as
  `model_dump(mode="json", by_alias=True, exclude_unset=True)` and a
  dataclass as `dataclasses.asdict()`, also when nested; `dazapiz` does not
  depend on pydantic.
- `verbose=True` logs requests and responses in `azr`'s format on the
  `dazapiz.http` logger, through `rich`, with long JSON bodies abbreviated
  as `azr`'s `format_json_body()`; headers are never logged. Log messages
  are plain text, so other handlers print no `rich` markup (#42).
- For tests: `ApiClient` takes keyword-only `transport=` (such as
  `httpx.MockTransport`) and `sleep=` (the function retries wait with),
  and has a read-only `credential` property.
  `dazapiz.testing.StaticTokenCredential` is a fake `TokenCredential` that
  returns a fixed token and records the scopes it was asked for.

### DuckDB

- `dazapiz.duckdb` (extra `duckdb`) registers DuckDB Azure secrets as
  `quak` does, named `dazapiz_default` or `dazapiz_<account>` and, with
  `account`, scoped to the account's `abfss://`, `abfs://`, `az://` and
  `azure://` hosts: `set_token_secret()`, `set_sp_secret()`,
  `set_chain_secret()`, and `set_credential_secret()`, which registers an
  access token from any `TokenCredential` and returns its `expires_on`.
  `list_secrets()` and `azure_settings()` return DuckDB relations;
  `tune()` sets the six Azure read and cache settings. The `azure`
  extension is installed and loaded when needed. `import dazapiz` never
  imports `duckdb`; without it, `dazapiz.duckdb` raises `ImportError`
  naming `pip install 'dazapiz[duckdb]'`.

### Errors and secrets

- `dazapiz.errors`: `DazapizError`, `RefreshTokenNotFoundError`,
  `UnsupportedPlatformError`, `ApiError`, `ResponseParseError`, and the
  `AzCliError` family. No refresh token, client secret, account key or
  bearer token appears in a `repr`, `str`, log record or error message.

### Documentation

- A site, <https://pedrobtz.github.io/py-dazapiz/>: a guide (get started,
  REST client with the Petstore example, DuckDB, browser-hosted sign-in,
  testing your API client) and an API reference.
