# Changelog

## 0.1.0 (unreleased)

- The package is renamed from `dazure` to `dazapiz` (import name,
  distribution, repository `pedrobtz/py-dazapiz`, `DazapizError`,
  `DAZAPIZ_*` environment variables, `dazapiz.*` loggers and the
  `dazapiz_default` token cache).
- `ApiClient` takes keyword-only `transport=` (an `httpx` transport, such
  as `httpx.MockTransport` in tests) and `sleep=` (the function retries
  wait with, default `time.sleep`), and has a read-only `credential`
  property, the credential it chose or `None` (#30).
- `dazapiz.testing.StaticTokenCredential`: a fake `TokenCredential` for
  tests without Azure, which returns a fixed token, records the scopes it
  was asked for in `.calls` and redacts the token in `repr` (#30).
- A guide page, "Testing your API client": an `ApiClient` subclass tested
  in CI with `respx` and `StaticTokenCredential`, fully offline
  (`pytest-socket`), including which credential `app_credential()` picks;
  its example, `examples/azure_petstore.py` and `examples/tests/`, runs in
  dazapiz's CI (#30).
- A documentation site, <https://pedrobtz.github.io/py-dazapiz/>, built with
  Great Docs: a guide (get started, REST client with the Petstore example,
  DuckDB, browser-hosted sign-in) and an API reference from NumPy
  docstrings, now on every public name (#27).
- `ApiClient.fetch(..., parse=f)` returns `f(body)`, typed as `f`'s result:
  `f` is applied to the parsed body of every successful response (an empty
  one as `None`) in place of `response_handler`, so
  `parse=Model.model_validate` or `TypeAdapter(list[Model]).validate_python`
  validates it. An exception from `f` raises the new
  `ResponseParseError`, which names the method and URL but not the body
  and is chained to the original (#26).
- A response body whose content type says JSON or XML but which does not
  parse raises `ResponseParseError` instead of the parser's own exception
  (#26).
- `fetch(json=...)` sends a pydantic model as
  `model_dump(mode="json", by_alias=True, exclude_unset=True)` and a
  dataclass as `dataclasses.asdict()`, also when nested in lists, tuples,
  dict values or dataclass fields; `dazapiz` does not depend on pydantic
  (#26).
- `with SomeApiClient() as client:` types `client` as the subclass (#26).
- `refresh_token_from_az_cli()` reports an `azureProfile.json` whose user
  name or tenant is not a string as having no default subscription,
  instead of returning it (#26).
- `examples/petstore.py` (in the repository): a typed Swagger Petstore v3
  client on `ApiClient` with pydantic models for request and response
  bodies (#26).
- `ApiClient(verbose=True)` abbreviates logged JSON bodies (request and
  failed response) as `azr`'s `format_json_body()`: more than 10 items keep
  the first and last 5, a nested array of more than 12 scalars the first
  and last 6, with a bare `...` between (#22).
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
- `DeviceCodeCredential` and `InteractiveBrowserCredential` subclass the
  `azure-identity` classes, keep their token cache in the platform store
  under the name `"dazapiz"` (`allow_unencrypted_storage=True` falls back
  to a plain file), and add `get_refresh_token()`, which signs in if
  needed and returns the refresh token from that cache.
- `az_account_show()`, `az_is_login()`, `az_login()` and `az_logout()` run
  the `az` found on `PATH`, with `--only-show-errors` and a 10-second
  timeout (none for `az_login()`). `az_login()` reuses an existing login
  (into `tenant_id`, if given) unless `force=True`; otherwise it runs
  `az login --use-device-code`, prints the device code and URL as `az`
  streams them, copies the code to the clipboard when a clipboard tool is
  found, and returns the account. Errors: `AzCliError` and its
  subclasses `AzCliNotFoundError`, `AzCliNotLoggedInError`,
  `AzCliNonInteractiveError` (no TTY or notebook kernel) and
  `AzCliTimeoutError`.
- `InteractiveBrowserCredential` with a redirect URI that is not on
  localhost signs in as `httr2::req_oauth_auth_code()` does: it prints
  the sign-in URL and reads back the callback URL, base64 JSON, or the
  code and state shown by the callback page, so it works from
  code-server and notebooks in the cloud.
- `ApiClient`, a small `httpx` client for one REST API, meant to be
  subclassed: `fetch()` fills `{name}` path placeholders (URL-encoded),
  retries 429, 503 and connection failures up to `max_tries` with
  `Retry-After` or `azr`'s backoff, parses JSON, XML or text by content
  type, and raises `ApiError` (an `httpx.HTTPStatusError`) with the
  method, URL, status and body. The bearer token is fetched from the
  credential once and renewed five minutes before expiry. `verbose=True`
  logs requests and responses in `azr`'s format on the `dazapiz.http`
  logger, through `rich`; headers are never logged.
- `app_credential()` chooses an API's credential from its own service
  principal variables (`client_id_env`, `client_secret_env`,
  `tenant_id_env`) and the mode (`prod`, `dev`, a single credential
  name, or automatic), from the argument or `$AZURE_TOKEN_CREDENTIALS`;
  a partly set service principal raises `ValueError` naming the missing
  variable. `ApiClient` subclasses call it when they set `client_id_env`
  and `client_secret_env`.
- `dazapiz.duckdb` (extra `duckdb`) registers DuckDB Azure secrets as
  `quak` does, named `dazapiz_default` or `dazapiz_<account>` and, with
  `account`, scoped to the account's `abfss://`, `abfs://`, `az://` and
  `azure://` hosts: `set_token_secret()`, `set_sp_secret()`,
  `set_chain_secret()`, and `set_credential_secret()`, which registers an
  access token from any `TokenCredential` (scope `STORAGE_SCOPE`) and
  returns its `expires_on`. `list_secrets()` and `azure_settings()`
  return DuckDB relations; `tune()` sets the six Azure read and cache
  settings. The `azure` extension is installed and loaded when needed.
  Values are quoted as DuckDB literals, and no secret appears in a log
  record or error. `import dazapiz` never imports `duckdb`; without it,
  `dazapiz.duckdb` raises `ImportError` naming `pip install 'dazapiz[duckdb]'`.
- `dazapiz.errors`: `DazapizError`, `RefreshTokenNotFoundError`,
  `UnsupportedPlatformError`, `ApiError`. No token appears in a `repr`,
  `str` or error message.
