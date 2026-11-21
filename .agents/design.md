# RFC 0078: `dazure`, the Azure helpers azure-identity lacks

Adopted from [RFC 0078](https://github.com/pedrobtz/packages/blob/c2a33fa70cbfe8a2b6d79c4fc70d036caf682d56/rfcs/not-started/0078-dazure-azure-helpers-for-python.md)
on 2026-11-21. This file is the single source of truth for the design; the
RFC is now a pointer here. Changed since adoption: §8 split into automated
and manual tiers (D23), with §4.3.2, §7, §9, D16 and D22 following;
§9's outline moved to [roadmap.md](roadmap.md) on 2026-11-21.

- **Status:** Proposed. The decisions in §10 marked "maintainer" were
  settled in conversation on 2026-11-19 (D21 on 2026-11-21); the rest
  are the author's calls and stay open until the package repository
  records them.
- **Date:** 2026-11-19.
- **Package:** `dazure`, a Python package (repository `pedrobtz/py-dazure`,
  import name `dazure`). This is the portfolio's first Python RFC; it
  follows `py-dazdiff`'s layout (`pyproject.toml` with hatchling, `uv`,
  ruff, pytest, Python >= 3.10). `dazure` is free on PyPI and there is no
  `pedrobtz/py-dazure` or `pedrobtz/dazure` repository, both checked on
  2026-11-19. `dependencies = ["azure-identity>=1.27", "httpx>=0.28",
  "rich>=13"]`;
  `azure-identity` brings `azure-core`, `msal` and `msal-extensions`.
  Extra `duckdb` adds `duckdb>=1.1`. No PySpark dependency: the Spark
  helper returns a plain `dict`. MIT.
- **Source:** the R package `azr` 0.3.7.9000 (`pedrobtz/azr` `main`,
  read 2026-11-19): `R/api-client.R`, `R/spark-conf.R`,
  `R/credential-azure-cli.R`, `R/credential-refresh-token.R`,
  `R/defaults.R`, `R/constants.R`. The R package `quak` (`origin/main`,
  read 2026-11-19): `R/azure.R`, `R/connection.R`. Wheels read on
  2026-11-19: `azure-core` 1.41.0, `azure-identity` 1.27.0, `msal`
  1.39.0, `msal-extensions` 1.3.1, `httpx` 0.28.1. Nothing has been
  built.

## 1. What dazure is

`dazure` brings to Python the parts of `azr` and `quak` that the Azure
SDK for Python does not already provide, and nothing else. It is a thin
layer: wherever `azure-identity` or `msal` already does a job,
`dazure` calls it rather than reimplementing it. The REST client is on
`httpx`; `azure-core` is used only for the `TokenCredential` and
`AccessToken` types.

```python
from dazure import az_login, spark_storage_conf, refresh_token_from_az_cli

az_login()                                 # device code, once per machine
conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
spark = SparkSession.builder.config(map=conf).getOrCreate()
```

> **Your `az login` in R and in Python, carried into Spark, DuckDB and
> any Azure REST API, with one small package on top of the official SDK.**

The main reason it exists is the second line. Neither PySpark nor the
Azure SDK will turn an `az login` into Spark's Hadoop ABFS configuration:
Hadoop ships `RefreshTokenBasedTokenProvider`, but the keys are set by
hand, and finding the refresh token means reading the Azure CLI's MSAL
cache and knowing it was issued to the CLI's own client ID. `azr`
already solves this in R (`azure_spark_storage_conf()`); `dazure` brings
it to PySpark users.

### 1.1 What dazure is not

- Not a second credential library. `DefaultAzureCredential`,
  `AzureCliCredential`, `ClientSecretCredential`,
  `ManagedIdentityCredential`, `WorkloadIdentityCredential`,
  `DeviceCodeCredential` and `InteractiveBrowserCredential` already
  exist and are used as they are; `azr`'s R6 equivalents are not
  ported. The only additions are `RefreshTokenCredential` and two thin
  subclasses that expose the refresh token `azure-identity` keeps
  private (§4.3). The browser one also signs in through a non-localhost
  callback page, as httr2 does (§4.3.3).
- Not a service SDK. `azr`'s storage, Microsoft Graph and Log Analytics
  clients are not ported: `azure-storage-file-datalake`, `msgraph-sdk`
  and `azure-monitor-query` cover them.
- Not `azr`'s `api_service` / `api_resource` layering. Only the base
  client comes over (§4.1).
- Not `azr`'s dataset, catalog and manifest classes.
- Not `quak`'s lake operations (`az_glob`, `az_exists`, `az_schema`,
  `az_glimpse`, `az_copy_to`, `az_write_parquet`, `az_delta_files`) or
  its DuckDB extension management. Those make a query toolkit, not an
  access layer; a later package can take them.

## 2. Scope

Six components plus one interface, in priority order. For each: where
it comes from, what Python already has, and what `dazure` adds.

1. **Spark / Hadoop ABFS config.** From
   `azr::azure_spark_storage_conf()`. Python has nothing. `dazure` adds
   the whole builder (§4.4).
2. **Refresh token from `az login`.** From `azr`'s `find_msal_token()`
   (same result, different lookup; §4.3)
   and `default_refresh_token()`. `msal.SerializableTokenCache` reads the
   cache file and `msal-extensions` decrypts it. `dazure` adds locating
   the cache and choosing the entry (§4.3).
3. **`RefreshTokenCredential`.** From `azr::RefreshTokenCredential`.
   `msal.PublicClientApplication.acquire_token_by_refresh_token()` does
   the exchange. `dazure` adds a `TokenCredential` wrapper (§4.3).
4. **A refresh-token interface.** `azr`'s credentials return an httr2
   token that carries `refresh_token`. `azure-identity` keeps refresh
   tokens private: `TokenCredential` returns access tokens only.
   `dazure` adds a `get_refresh_token()` protocol and thin subclasses of
   `InteractiveBrowserCredential` and `DeviceCodeCredential` that
   implement it (§4.3). The browser subclass also adds httr2's
   pasted-code sign-in for a redirect URI that is not on localhost,
   which `azure-identity` cannot do (§4.3.3).
5. **REST client.** From `azr::api_client`. `httpx` is the HTTP layer
   and logs each call on the `httpx` logger; `azure-identity` supplies
   tokens. `dazure` adds the bearer `httpx.Auth`, retry with backoff,
   `fetch()` with path templates and content-type parsing, the
   coloured request/response logging, and per-API credentials: a
   subclass picks the developer's login or a service principal from its
   own environment variables (§4.1).
6. **`az` CLI helpers.** From `azr::az_cli_login()` and its siblings.
   `AzureCliCredential` runs `az account get-access-token` only. `dazure`
   adds login, logout, is-logged-in and account show (§4.2).
7. **DuckDB Azure secrets and tuning.** From `quak::az_set_*_secret()`,
   `az_list_secrets()`, `az_conn_settings()` and `az_tune()`. The
   `azure` extension exists; secrets are raw SQL. `dazure` adds typed
   helpers, per-account scoping and secrets from any `TokenCredential`
   (§4.5).

## 3. Design principles

1. **The SDK first.** Anything `azure-identity` or `msal` does is used,
   not redone. A `dazure` function that wraps one says so
   in its docstring.
2. **Any `TokenCredential` works.** Wherever a credential is taken, the
   type is `azure.core.credentials.TokenCredential`, so
   `DefaultAzureCredential()` and `dazure.RefreshTokenCredential` are
   interchangeable.
3. **Secrets never print.** Refresh tokens, client secrets, account keys
   and bearer tokens are redacted in `repr`, `str`, logs and error
   messages (§6).
4. **Same behaviour as azr where the R behaviour is a fix.** `azr`'s Spark
   builder carries hard-won details (the refresh provider reads
   `refresh.token.endpoint`, not `client.endpoint`; the MSI authority
   needs a trailing `/`). These are ported with the comments that explain
   them, and tested by key-for-key comparison with `azr` (§8).
5. **Engines optional.** Neither Spark nor DuckDB is required to install
   `dazure`. DuckDB is an extra, imported lazily.

## 4. Components

### 4.1 `ApiClient`

One class, ported from `azr::api_client` with the service and resource
layers dropped (maintainer), on `httpx` (maintainer). It is meant to be
subclassed once per API, and the subclass decides where its credentials
come from (maintainer): in development the developer's own login, in
production a service principal whose ID and secret are in
API-specific environment variables (§4.1.1).

```python
class ApiClient:
    host_url: ClassVar[str | None] = None
    scope: ClassVar[str | None] = None    # default: f"{host_url}/.default"
    client_id_env: ClassVar[str | None] = None      # e.g. "APP_API_CLIENT_ID"
    client_secret_env: ClassVar[str | None] = None  # e.g. "APP_API_SECRET"
    tenant_id_env: ClassVar[str] = "AZURE_TENANT_ID"
    mode: ClassVar[str | None] = None               # see §4.1.1

    def __init__(
        self,
        host_url: str | None = None,      # overrides the class attribute
        credential: TokenCredential | None = None,
        scope: str | None = None,
        *,
        timeout: float = 60,
        connect_timeout: float = 30,
        max_tries: int = 5,
        verbose: bool = False,
        response_handler: Callable[[Any], Any] | None = None,
    ): ...

    def fetch(
        self,
        path: str,                         # "/subscriptions/{subscription_id}"
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,   # override parsing
        **path_params: str,
    ) -> Any: ...

    def close(self) -> None: ...           # also a context manager
```

The client holds one `httpx.Client(base_url=host_url,
timeout=httpx.Timeout(timeout, connect=connect_timeout))`.

**Auth.** `BearerAuth(httpx.Auth)` calls `credential.get_token(scope)`,
keeps the `AccessToken` until five minutes before `expires_on`, and sets
`Authorization: Bearer …`. A 401 is not replayed:
`TokenCredential.get_token()` has no force-refresh, so a replay would
send the same token again; the cached token is dropped so the next call
asks the credential afresh. The credential is, in order: the
`credential` argument; else `app_credential(...)` (§4.1.1) with the
class's variable names and mode, when the class sets `client_id_env`
and `client_secret_env`, called in `__init__`, so the choice is made
from the environment as it is when the client is created and kept for
the instance's life (only the first token is fetched lazily, on the
first request); else none, and the client sends requests
unauthenticated, as `azr`'s `default_non_auth` does.

#### 4.1.1 Per-API credentials: `app_credential()`

```python
class AppApiClient(ApiClient):
    host_url = "https://app-api.example.com"
    scope = "api://00000000-0000-0000-0000-000000000000/.default"
    client_id_env = "APP_API_CLIENT_ID"
    client_secret_env = "APP_API_SECRET"
    # tenant_id_env = "APP_API_TENANT"   # only if not AZURE_TENANT_ID

client = AppApiClient()                                    # chosen by mode
client = AppApiClient(credential=DefaultAzureCredential())  # or given

def app_credential(
    client_id_env: str,
    client_secret_env: str,
    *,
    tenant_id_env: str = "AZURE_TENANT_ID",
    mode: str | None = None,
) -> TokenCredential: ...
```

The variable names are given in full rather than built from a prefix
(maintainer), so an API can use whatever names its deployment already
has (`APP_API_SECRET`, `MYAPP_SP_PASSWORD`, ...). The tenant usually is
the organisation's, so it defaults to `AZURE_TENANT_ID` and is named
only when an API's service principal lives in another tenant.

`azure-identity` already composes chains (`ChainedTokenCredential`) and
already switches `DefaultAzureCredential` between groups with
`AZURE_TOKEN_CREDENTIALS=dev|prod`, as `azr`'s `default_credential_chain()`
does. What it has no way to say is "this API's service principal is in
`APP_API_CLIENT_ID` and `APP_API_SECRET`": its `EnvironmentCredential`
reads `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` and `AZURE_TENANT_ID`
only, and the first two usually belong to the machine or another app.
`app_credential()` fills that gap and builds everything else from
`azure-identity` classes unchanged.

It is a decision made up front, not a chain, because `azure-identity`'s
`ChainedTokenCredential` cannot express "the service principal if its
variables exist" the way `azr`'s `credential_chain()` does. `azr`'s
chain holds classes and skips one whose settings are missing; the Python
chain holds built instances, `ClientSecretCredential` raises
`ValueError` at construction when any of its three values is missing,
and the chain moves on only after `CredentialUnavailableError`, so a
rejected secret ends it (`_credentials/chained.py`, 1.27.0). So
`app_credential()` reads the variables and returns one credential; the
only `ChainedTokenCredential` it builds is the `dev` one, where
`AzureCliCredential` raises `CredentialUnavailableError` when nobody is
logged in and the chain correctly moves on to the device code.

The mode is the `mode` argument (or class attribute), else
`AZURE_TOKEN_CREDENTIALS`, else automatic:

- **`prod`**: the first that applies of
  1. `ClientSecretCredential` from the three named variables, when all
     three are set;
  2. `WorkloadIdentityCredential()`, when `AZURE_FEDERATED_TOKEN_FILE`
     is set;
  3. `ManagedIdentityCredential()`.

  Workload and managed identity read the standard `AZURE_*` variables
  through `azure-identity` itself (maintainer): the named variables are
  for the service principal only. A client ID without a secret, or the
  reverse, is an error naming the missing variable, never a silent
  fall-through; so is both set with no tenant.
  `prod` never uses a developer login.
- **`dev`**: `ChainedTokenCredential(AzureCliCredential(),
  dazure.DeviceCodeCredential())`, the device code tried only in an
  interactive session (a TTY or a notebook kernel), so a batch job fails
  instead of waiting for a prompt.
- **A single name**: `client_secret` (the named service principal),
  `workload_identity`, `managed_identity`, `azure_cli` or `device_code`,
  matched case-insensitively, as `azr` and `azure-identity` accept
  single names in `AZURE_TOKEN_CREDENTIALS`.
- **Automatic** (nothing set): `prod`'s service principal when the
  client ID and secret variables are set, otherwise `dev`. A developer
  with neither set gets their own login; a deployment that sets them
  gets the service principal; a deployment that relies on managed or
  workload identity sets `AZURE_TOKEN_CREDENTIALS=prod`, or the class
  sets `mode = "prod"`.

Different API classes in one process each read their own variables, so
two APIs can use two service principals side by side. The chosen mode
and credential class (never a value) are logged on the `dazure.http`
logger at `INFO` when the credential is built, so `verbose=True` shows
which login a client is using.

**Retry.** `httpx` retries only failed connections
(`HTTPTransport(retries=...)`), so `fetch()` carries its own loop, as
`azr` gets from `httr2::req_retry()`, with the same rules: up to
`max_tries` attempts on connection failures and on 429 and 503 (httr2's
default transient set), for every method; 500, 502, 504 and read
timeouts are not retried, so a `POST` or `PUT` with a side effect is
never resent after the server may have acted on it. The wait is
`Retry-After` when the response gives one, otherwise `azr`'s
`backoff_default()`: uniform between 1 and 2.5^attempt seconds, capped
at 60. Each retry is
logged as a warning with the wait and the attempt number.

**Parsing.** `fetch()` fills `{name}` placeholders from `path_params`
(URL-encoded; a missing or unused parameter is a `ValueError`), sends
the request and parses the body by content type: `application/json` to
Python objects, `application/xml` to `xml.etree.ElementTree.Element`,
anything else to `str`, an empty body to `None`. The result then goes
through `response_handler`. `azr`'s default handler converts data frames
to `data.table`; the Python default is the identity. A non-2xx response
after retries raises `dazure.ApiError`, an `httpx.HTTPStatusError`
subclass whose message carries the method, URL, status and response
body.

**Logging.** `httpx`'s own logging is one plain `INFO` line per call
on the `httpx` logger, `HTTP Request: GET <url> "HTTP/1.1 200 OK"`, with
no request body, no timing, no size, no error body and no colour; its
`httpcore` `DEBUG` records are transport noise. That is not what `azr`
shows, so `dazure` adds `httpx` event hooks (about 30 lines, prototyped
on 2026-11-19) that reproduce `azr`'s format:

```text
ℹ >>> POST https://management.azure.com/x
ℹ >>> body:
{
  "name": "rg1",
  "location": "westeurope"
}
✖ <<< status = 500 | time = 0.21 secs. | size = 0.04 Kb
✖ <<< body:
{
  "error": { "code": "Boom", "message": "bad" }
}
⚠ Request failed. Retrying in 2 secs. (attempt 2 of 5).
```

The request hook logs method and URL, then the JSON request body
pretty-printed; the response hook logs status, elapsed time and size
(green on success) and, on failure, the response body (red); the retry
loop logs its waits (yellow). Timing is taken with `time.perf_counter()`
stored in `request.extensions` by the request hook, because
`response.elapsed` raises inside a response hook until the response is
closed (found by the prototype).

The hooks write to a `dazure.http` logger, so the records can be routed
or silenced like any other. `verbose=True` turns them on and, if the
logger has no handler yet, attaches `rich.logging.RichHandler(markup=True,
show_time=False, show_level=False, show_path=False)`, which prints the
lines above with `rich`'s colours and JSON highlighting. The `httpx`
logger is left alone so its line does not duplicate `>>>`. The hooks
never log headers, so the bearer token cannot appear; bodies are logged
as sent, so a caller posting secrets in a body should leave `verbose`
off.

### 4.2 `az` CLI helpers

Plain `subprocess` wrappers, found through `shutil.which("az")`; a
missing `az` raises `AzCliNotFoundError` with an install hint.

- `az_account_show()` runs `az account show --output json` and returns
  a `dict`, or raises `AzCliNotLoggedInError`.
- `az_is_login()` runs the same command and returns a `bool`.
- `az_login(tenant_id=None, *, force=False)` runs
  `az login --use-device-code [--tenant ...] --output json` and returns
  the account `dict`.
- `az_logout()` runs `az logout` and returns `None`.

`az_login()` returns the current account without prompting when already
logged in (into `tenant_id`, if given) unless `force=True`. Otherwise it
starts `az` with `subprocess.Popen`, reads stderr line by line until the
device-code message appears, prints the code and URL (and copies the
code to the clipboard when a clipboard tool is found, as `azr` does),
then waits for the process to finish. It refuses to run when
`sys.stdin` is not a TTY and no notebook kernel is detected, raising
`AzCliNonInteractiveError`, as `azr` refuses outside an interactive
session. Every helper takes `timeout` (default 10 s; `az_login` has
none by default) and runs `az` with `--only-show-errors`.

Getting tokens from the CLI is not wrapped: that is
`azure.identity.AzureCliCredential`.

### 4.3 Refresh tokens

`azr` gives one interface across its credentials: `get_token()` returns
an httr2 token, and for the user flows that token carries
`refresh_token`. In Python the shared interface is
`azure.core.credentials.TokenCredential`, which every `azure-identity`
class implements, and `dazure` takes it wherever an access token is
needed (principle 2). But `azure-identity` deliberately exposes no
refresh token: `AccessToken` / `AccessTokenInfo` hold the access token,
expiry and refresh time only, and the interactive credentials keep their
refresh tokens in a private MSAL cache. `dazure` therefore adds one
interface, only for the credentials that can have a refresh token:

```python
@dataclass(frozen=True)
class RefreshTokenInfo:           # repr redacts `token`
    token: str
    client_id: str
    tenant_id: str
    username: str | None = None

    def get_refresh_token(self) -> RefreshTokenInfo:
        return self

class SupportsRefreshToken(Protocol):
    def get_refresh_token(self) -> RefreshTokenInfo: ...

AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
```

`spark_storage_conf()`, `RefreshTokenCredential` and the DuckDB helpers
accept a plain string or any `SupportsRefreshToken`, so the token always
arrives with the client ID and tenant it belongs to. Four things
implement it. Service-principal, managed and workload identity never
receive a refresh token, because their flows do not issue one, so they
do not.

#### 4.3.1 From `az login`: `refresh_token_from_az_cli()`

```python
def refresh_token_from_az_cli(
    *, username: str | None = None, tenant_id: str | None = None,
    config_dir: str | os.PathLike | None = None,
) -> RefreshTokenInfo: ...
```

The result is the account the Azure CLI is signed in as, as in `azr`.
`azr` gets there by running `az account get-access-token` and matching
that token in the cache to its `home_account_id`; `dazure` reaches the
same account without running `az`, so it also works where `az` is not
installed but its config directory is (a mounted `~/.azure`):

1. The config directory is `config_dir`, else `$AZURE_CONFIG_DIR`, else
   `~/.azure`.
2. `azureProfile.json` gives the current account: the subscription with
   `isDefault: true`, its `user.name` and `tenantId`. `username` and
   `tenant_id` override these.
3. `msal_token_cache.json` is loaded into `msal.SerializableTokenCache`.
   The `Account` entries with that `username` give a `home_account_id`
   (one per person, shared by the tenants they are a guest in); the
   refresh token is the `RefreshToken` entry with that
   `home_account_id` and `client_id == AZURE_CLI_CLIENT_ID`. Refresh
   tokens carry no tenant, so the tenant is returned from the profile,
   not from the token.
4. No profile, no default subscription or no matching token raises
   `RefreshTokenNotFoundError` ("run `az login`"), naming the file and
   the username looked for, never a token.

macOS and Linux only (maintainer). On Windows the CLI signs in through
the Windows broker by default and the function raises
`UnsupportedPlatformError` pointing to §4.3.2 and to
`$AZURE_REFRESH_TOKEN`. The cache file is only read, never written:
`azr::write_msal_token()` is not ported.

#### 4.3.2 From an interactive sign-in

`dazure.InteractiveBrowserCredential` and `dazure.DeviceCodeCredential`
subclass the `azure-identity` classes of the same name and add
`get_refresh_token()`. They are the Python counterparts of `azr`'s
`AuthCodeCredential` and `DeviceCodeCredential`, and they work on every
platform, Windows included.

- Constructed with `cache_persistence_options=
  TokenCachePersistenceOptions(name="dazure",
  allow_unencrypted_storage=...)`, a public `azure-identity` option, so
  the parent class writes its MSAL cache to the platform store: a file
  under `%LOCALAPPDATA%\.IdentityService\` protected by DPAPI on
  Windows, the Keychain on macOS, libsecret on Linux, or a plain file
  under `~/.IdentityService/` on Linux when `allow_unencrypted_storage`
  is set and libsecret is unusable (headless machines).
- The client ID is `azure-identity`'s default,
  `DEVELOPER_SIGN_ON_CLIENT_ID`, which is the same Azure CLI client ID
  `azr` uses, unless the caller passes another.
- `get_refresh_token()` calls `authenticate()` if the credential has no
  `AuthenticationRecord` yet (this is where the user signs in), then
  opens the same persisted cache read-only with `msal-extensions` and
  returns the `RefreshToken` entry for the record's `home_account_id`
  and client ID, with the record's tenant and username. Both the
  `.nocae` and `.cae` caches are searched.
- Opening the cache means building the same `msal_extensions`
  persistence `azure-identity` builds in its private
  `_persistent_cache._get_persistence()` (file name `dazure.nocae`,
  Keychain service `Microsoft.Developer.IdentityService`, libsecret
  attribute `MsalClientID`). That layout is `azure-identity`'s
  implementation detail, not a documented API, so a manual test signs
  in for real on each OS with the installed `azure-identity` and reads
  the token back (§8.2); it is rerun whenever `azure-identity` moves.
  The private argument `_cache`, which would avoid the persisted store,
  is not used.

#### 4.3.3 Sign-in through a callback page: httr2's pasted code

`azure-identity` cannot do the sign-in that `httr2::req_oauth_auth_code()`
does when the redirect URI is not on localhost, which is the one that
works from a browser-hosted session such as code-server, RStudio Server
or a notebook in the cloud. This R call is the model:

```r
req_oauth_auth_code(
  client, auth_url = ".../oauth2/v2.0/authorize",
  scope = "User.Read offline_access",
  redirect_uri = "https://your-domain.example/azure-callback",
  cache_disk = TRUE
)
```

httr2 1.3.0 (`oauth_flow_auth_code()`) sends PKCE (S256) and a random
`state`. A localhost redirect gets a local listener; any other redirect
prints the authorize URL and reads back what the callback page shows
(`oauth_flow_auth_code_read()`): the full callback URL, base64-encoded
JSON with `code` and `state`, or the bare code followed by the state
when asked. The state is always checked. `cache_disk = TRUE` keeps the
token, refresh token included, so later sessions do not sign in again.

`azure-identity` 1.27.0 has the pieces but not the flow.
`InteractiveBrowserCredential` rejects a redirect URI without a port
and binds an HTTP server to the redirect's host, so it can only receive
the code on the machine running Python. In code-server that is the
remote host, which the user's browser never reaches.
`AuthorizationCodeCredential` takes a code the caller already has, with
no authorize URL, no PKCE and no persisted cache.

`dazure.InteractiveBrowserCredential` therefore follows httr2's rule:

- **Localhost redirect, or none.** Unchanged `azure-identity`
  behaviour: a local listener and the system browser.
- **Any other redirect URI.** The redirect URI is kept by `dazure`
  (not passed to the parent, whose check would reject it), and only
  `_request_token()` is overridden. It calls the parent's MSAL app
  (`_get_app()`) for `initiate_auth_code_flow(scopes, redirect_uri=...,
  response_mode="query", prompt="select_account", login_hint=...,
  claims_challenge=...)`, which builds the PKCE pair, state and nonce.
  It prints the authorize URL, reads the callback URL, base64 JSON or
  code and state as httr2 does, and redeems them with
  `acquire_token_by_auth_code_flow()`, which checks the state. A state
  mismatch, which MSAL raises as `ValueError`, becomes
  `ClientAuthenticationError`.

Everything else is inherited, so this flow uses the same cache as the
rest of §4.3.2 and needs nothing new from the MSAL side. The
`cache_persistence_options` store is `cache_disk = TRUE`;
`AuthenticationRecord`, silent refresh, CAE and tenant handling come
from the parent; `get_refresh_token()` works the same way. As in httr2,
the prompt needs an interactive session (a TTY or a notebook kernel);
otherwise the credential raises `CredentialUnavailableError` instead of
waiting. Two differences from httr2 are forced by MSAL: `offline_access`,
`openid` and `profile` are reserved scopes that MSAL adds itself and
rejects if given, so `scopes=["User.Read"]` stands for httr2's
`"User.Read offline_access"`; and the app registration must allow
public-client redemption for that redirect URI (no client secret is
sent), as httr2's call without a secret already requires.

The mechanism is general, as httr2's is: nothing in it is tied to one
client ID, app or page. Packages that ship this flow for a single app
hard-code three things, and `dazure` takes all three as arguments:

- **The app.** Any Entra app registration whose redirect URI is
  registered as a public client ("Mobile and desktop applications"), so
  the code is redeemed without a secret, as httr2's call without a
  secret is. A "Web" redirect needs a client secret and an "SPA" one
  must be redeemed from the browser, so neither works without a secret.
  A confidential client is out of scope; httr2 supports one, and
  §11 keeps it open.
- **The redirect URI.** Any URL the user's browser can load. MSAL does
  not contact it; it only has to match the registration. The code-server
  URL itself works, as does a static page on any host.
- **The callback page.** It only has to let the user copy the code. A
  page that shows `?code=...&state=...`, or the httr2 page that shows
  them as base64 JSON, is convenient. A page that does not exist, or
  returns 404, also works, because the user can paste the URL from the
  address bar, which is the first reply form. `dazure` ships no page.

Tenant (GUID, domain, `organizations` or `common`), scopes and
`authority_host` (sovereign clouds) are the parent's arguments
unchanged.

```python
from dazure import InteractiveBrowserCredential

cred = InteractiveBrowserCredential(
    tenant_id="11111111-2222-3333-4444-555555555555",
    client_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    redirect_uri="https://your-domain.example/azure-callback",
)
token = cred.get_token("User.Read").token   # prompts once, then silent
me = httpx.get("https://graph.microsoft.com/v1.0/me",
               headers={"Authorization": f"Bearer {token}"}).json()
```

A prototype against `azure-identity` 1.27.0 and `msal` 1.39.0
(2026-11-21) took this path through the parent's `get_token()`: the
persisted cache was configured, the silent lookup ran first, the
override built the authorize URL with the external redirect URI,
`S256` challenge, state and nonce, and a pasted callback URL with the
wrong state was refused. Redeeming a real code was not tried.

#### 4.3.4 From a token you already have

`$AZURE_REFRESH_TOKEN`, which `azr` reads as `default_refresh_token()`,
is honoured by `spark_storage_conf()` and `RefreshTokenCredential` when
no token is passed, for CI and containers. A plain string gets
`$AZURE_CLIENT_ID`, else the CLI client ID, and `$AZURE_TENANT_ID`, else
`"common"`, as in `azr`. Nothing reads a cache implicitly: callers pass
`refresh_token_from_az_cli()` or a credential, as in §1, so a function
that assembles keys never reads the disk.

#### 4.3.5 `RefreshTokenCredential`

`RefreshTokenCredential(refresh_token=None, *, authority_host=None)`
takes a string or a `SupportsRefreshToken`, and implements both
`TokenCredential` and `SupportsRefreshToken`. `get_token(*scopes)` uses
`msal.PublicClientApplication(client_id, authority=...)
.acquire_token_by_refresh_token(refresh_token, scopes)`, caching the
access token in memory until five minutes before expiry and keeping the
rotated refresh token MSAL returns, which `get_refresh_token()` then
gives back. It is what lets the REST client and the DuckDB helper use a
refresh token without `az` or a browser at run time, for example inside
a Spark executor or a container.

### 4.4 `spark_storage_conf()`

A port of `azr::azure_spark_storage_conf()`, key for key when
arguments are passed explicitly; the defaults differ where `azr`'s are
wrong, as listed below.

```python
def spark_storage_conf(
    auth_type: Literal["refresh_token", "client_secret", "workload_identity",
                       "managed_identity", "shared_key"] = "refresh_token",
    *,
    storage_account: str | None = None,
    tenant_id: str | None = None,        # $AZURE_TENANT_ID, else "common"
    client_id: str | None = None,        # see the defaults below
    client_secret: str | None = None,    # $AZURE_CLIENT_SECRET
    refresh_token: str | SupportsRefreshToken | None = None,  # §4.3.4
    account_key: str | None = None,
    token_file: str | None = None,       # $AZURE_FEDERATED_TOKEN_FILE
    authority_host: str = "login.microsoftonline.com",  # $AZURE_AUTHORITY_HOST
    prefix: str | None = "spark.hadoop",
) -> SparkStorageConf: ...
```

Keys set under `fs.azure.account.`, by `auth_type`:

- `client_secret`: `auth.type=OAuth`,
  `oauth.provider.type=…ClientCredsTokenProvider`, `oauth2.client.id`,
  `oauth2.client.secret`, `oauth2.client.endpoint`.
- `refresh_token`: `auth.type=OAuth`,
  `oauth.provider.type=…RefreshTokenBasedTokenProvider`,
  `oauth2.client.id`, `oauth2.refresh.token`,
  `oauth2.refresh.token.endpoint`.
- `workload_identity`: `auth.type=OAuth`,
  `oauth.provider.type=…WorkloadIdentityTokenProvider`,
  `oauth2.client.id`, `oauth2.msi.tenant`, `oauth2.token.file`,
  `oauth2.msi.authority`.
- `managed_identity`: `auth.type=OAuth`,
  `oauth.provider.type=…MsiTokenProvider`, `oauth2.client.id`,
  `oauth2.msi.tenant`, `oauth2.msi.authority`.
- `shared_key`: `auth.type=SharedKey`, `key`; requires
  `storage_account`.

Provider classes live in `org.apache.hadoop.fs.azurebfs.oauth2`. Token
endpoints are `https://{authority_host}/{tenant_id}/oauth2/v2.0/token`
(the `refresh_token` type must use `refresh.token.endpoint`, which is
what the Hadoop provider reads). The MSI authority is
`https://{authority_host}/` with the trailing slash, because Hadoop
concatenates it with the tenant. With `storage_account`, each key gets
the account's DFS host as a suffix: a short name is expanded with
`dfs.core.windows.net`, `dfs.core.usgovcloudapi.net` or
`dfs.core.chinacloudapi.cn` according to `authority_host`; a name with a
dot is used as is. With `prefix=None`, keys are the raw `fs.azure.*`
form for `core-site.xml` or `hadoopConfiguration().set()`.

Defaults when `client_id` or `tenant_id` is not passed:

- `refresh_token`: a `SupportsRefreshToken` supplies its own client ID
  and tenant. A plain string uses the §4.3.4 defaults, as `azr` does.
- `client_secret`: `$AZURE_CLIENT_ID` and `$AZURE_TENANT_ID`; missing
  either is a `ValueError`. (`azr` falls back to the CLI client ID,
  which cannot hold a secret.)
- `managed_identity`: `$AZURE_CLIENT_ID` if set, else the key is
  left out, which Hadoop reads as the system-assigned identity. (`azr`
  writes the CLI client ID, which asks IMDS for a user-assigned identity
  that does not exist.)
- `workload_identity`: `$AZURE_CLIENT_ID` and `$AZURE_TENANT_ID`, which
  the AKS webhook sets; missing either is a `ValueError`. (`azr` falls
  back to the CLI client ID, which the federated token cannot match.)

A refresh token used with the wrong client ID fails only later, inside
a Spark executor with a Hadoop-shaped error; returning the client ID
with the token is what prevents that.

`SparkStorageConf` is a `dict[str, str]` subclass whose `__repr__` and
`__str__` replace the values of `*.oauth2.client.secret`,
`*.oauth2.refresh.token` and `*.key` with `"<redacted>"`; the dict
itself holds the real values so it can be passed to
`SparkSession.builder.config(map=...)` or `spark.conf.set`.
`workload_identity` notes in its docstring that it needs Hadoop 3.4.1+
(Spark 4.x, Databricks 14.3+ LTS, Synapse 3.4+), as `azr` documents.

### 4.5 DuckDB secrets and tuning

In `dazure.duckdb`, needing the `duckdb` extra. Each helper takes a
`duckdb.DuckDBPyConnection`, runs `INSTALL azure; LOAD azure` if needed,
and executes the same `CREATE OR REPLACE SECRET` statements as `quak`,
with values bound as parameters or quoted with DuckDB's literal rules,
never interpolated raw.

```python
set_token_secret(conn, token, account=None)
set_credential_secret(conn, credential, account=None, scope=STORAGE_SCOPE)
set_sp_secret(conn, tenant_id, client_id, client_secret, account=None)
set_chain_secret(conn, account=None, chain="default")
list_secrets(conn)
azure_settings(conn)
tune(conn, *, concurrency=None, chunk_size=None, buffer_size=None,
     transport=None, metadata_cache=None, context_cache=None)
```

| Function | quak | DuckDB provider or source |
| --- | --- | --- |
| `set_token_secret` | `az_set_token_secret` | `access_token` |
| `set_credential_secret` | new | `access_token` from `get_token(scope)` |
| `set_sp_secret` | `az_set_sp_secret` | `service_principal` |
| `set_chain_secret` | `az_set_chain_secret` | `credential_chain` |
| `list_secrets` | `az_list_secrets` | `duckdb_secrets()` |
| `azure_settings` | `az_conn_settings` | `duckdb_settings()` |
| `tune` | `az_tune` | `SET` of six `azure_*` and cache settings |

`STORAGE_SCOPE` is `https://storage.azure.com/.default`.

Secrets are named `dazure_default` or `dazure_<account>` (non-
alphanumerics to `_`), so that `quak`'s and `dazure`'s secrets never
collide in a shared DuckDB file. With `account`, the secret gets
`ACCOUNT_NAME` where the provider takes one and a `SCOPE` list of the
account's `abfss://`, `abfs://`, `az://` and `azure://` host prefixes,
which DuckDB matches as plain string prefixes, as `quak` does.
`quak`'s caveat carries over in the docstrings: Delta tables never match
an account-scoped secret, so register an unscoped one for them.

`set_credential_secret()` is the bridge to §4.3: DuckDB's own
`credential_chain` cannot use an `az login` refresh token, but
`set_credential_secret(conn, RefreshTokenCredential(...))` can. The
access token it registers expires (typically after an hour); the
function returns the token's `expires_on` and does not refresh it in
the background. Calling it again replaces the secret.

## 5. Public API summary

```python
from dazure import (
    ApiClient, app_credential,
    az_login, az_logout, az_is_login, az_account_show,
    RefreshTokenInfo, SupportsRefreshToken, AZURE_CLI_CLIENT_ID,
    refresh_token_from_az_cli, RefreshTokenCredential,
    InteractiveBrowserCredential, DeviceCodeCredential,
    spark_storage_conf, SparkStorageConf,
)
from dazure.duckdb import (
    set_token_secret, set_credential_secret, set_sp_secret, set_chain_secret,
    list_secrets, azure_settings, tune,
)
```

Errors derive from `dazure.DazureError`; `dazure.ApiError` also derives
from `httpx.HTTPStatusError`. `ClientAuthenticationError` from a
credential passes through unwrapped.
Names are snake_case Python names; `azr`'s `az_cli_` prefix is shortened
to `az_` because the module already says Azure.

## 6. Handling secrets

- No token, key or secret that `dazure` handles appears in `repr`,
  `str`, exception messages or log records. Tests assert this for every
  component by searching output for a sentinel value.
- The one exception is deliberate: with `verbose=True`, `ApiClient` logs
  request bodies, and response bodies on failure, as sent, because they
  are what debugging needs (maintainer). A secret the caller puts in a
  body is the caller's to keep out of a verbose session.
- HTTP logging never includes headers, so the bearer token never appears
  (§4.1).
- The MSAL cache is opened read-only and never copied to a temporary
  file.
- `az_login()` prints the device code, which is meant to be seen, and
  nothing from the login JSON beyond the account name.

## 7. Packaging

Repository `pedrobtz/py-dazure`, laid out like `py-dazdiff`: `src/dazure/`,
`tests/`, `pyproject.toml` (hatchling), `uv.lock`, `CHANGELOG.md`,
`ruff` with the same rule set, typed (`py.typed`). Python 3.10 to 3.14,
matching `azure-identity`'s floor. CI on Ubuntu, macOS and Windows,
for the platform branches (`UnsupportedPlatformError` on Windows, the
config and cache paths); the real persisted cache of §4.3.2 is checked
by hand on each OS (§8.2). Published
to PyPI by a release workflow with trusted publishing, as `py-dazdiff`
does.

## 8. Testing and validation

Two tiers (D23, maintainer, 2026-11-21). Most Azure behaviour is tested
by hand in an environment with full Azure access. Automated tests cover
what needs no Azure at all, or only a mock that is simple: plain data,
`httpx.MockTransport`, a fake `az` on `PATH`, or one `msal` method
patched. A test that would need a fake Entra authority (OIDC discovery,
instance discovery, token and ID-token responses through
`azure-identity`'s pipeline) or a real OS secret store on a CI runner is
not simple, and is manual instead.

### 8.1 Automated (CI, no Azure)

- **Spark config against `azr`.** A fixture generated by running
  `azr::azure_spark_storage_conf()` over every `auth_type` x
  `storage_account` (none, short, FQDN) x `authority_host` (public, US
  Gov, China) x `prefix` (default, `NULL`), stored as JSON with
  placeholder secrets and every argument passed explicitly.
  `spark_storage_conf()` must reproduce it exactly. The default paths,
  where `dazure` deliberately differs from `azr` (§4.4), have their own
  tests.
  The generator script lives in `tools/` and is rerun when `azr` changes.
- **MSAL cache.** Synthetic `azureProfile.json` and
  `msal_token_cache.json` pairs: no login, one account, several accounts
  (work and guest), one person in several tenants; Windows raises
  `UnsupportedPlatformError`.
- **`RefreshTokenCredential`.** `msal` mocked at
  `acquire_token_by_refresh_token`: caching, expiry margin, token
  rotation, error mapping.
- **Interactive credentials, without signing in.** The cache read of
  §4.3.2 against a plain-file persistence written by the test (the
  unencrypted Linux layout), so the entry selection by
  `home_account_id`, client ID, `.nocae` and `.cae` is checked. Whether
  `azure-identity` really writes that layout is manual (§8.2).
- **Pasted-code sign-in, without an authority.** The reply parser on
  each of httr2's three forms (callback URL, base64 JSON, code then
  state), an `error` query, and garbage; the redirect rule (localhost or
  none goes to the parent, anything else to the pasted flow); no TTY
  raises `CredentialUnavailableError`. `initiate_auth_code_flow()` and
  `acquire_token_by_auth_code_flow()` patched on the MSAL app: the
  printed URL is the one MSAL built, the state goes back to MSAL, and its
  `ValueError` becomes `ClientAuthenticationError`.
- **`app_credential()`.** Every mode and every partly set case, with
  `azure-identity` classes checked by type and constructor arguments
  (no sign-in), and the interactive check faked.
- **`ApiClient`.** `httpx.MockTransport`: path templating and encoding,
  content-type parsing, retry rules and `Retry-After`, no
  `Authorization` value in captured log records, `ApiError` body.
- **`az` helpers.** A fake `az` script on `PATH` that emits recorded
  outputs, including a device-code login that streams its prompt.
- **DuckDB.** A real in-memory DuckDB with the `azure` extension: the
  generated SQL is checked through `duckdb_secrets()` (redacted by
  DuckDB). `INSTALL azure` downloads from `extensions.duckdb.org`, so CI
  caches the extension directory keyed on the DuckDB version and the
  tests themselves make no network calls.
- **Secrets.** The sentinel search of §6 over every component above.

### 8.2 Manual (an environment with full Azure access)

Written as a checklist in `tests/manual/README.md`, with a script per
item where one helps, skipped by pytest unless `DAZURE_LIVE=1`. Run
before every release and whenever the `azure-identity` or `msal` floor
or lock moves, because the private details these items guard (§4.3.2,
§4.3.3) are what a new release can change. Each run is recorded with
date, OS and versions in the release's pull request.

- **`az login` refresh token** (macOS, Linux): `refresh_token_from_az_cli()`
  after a real `az login`, including a guest tenant; the token is
  redeemed by `RefreshTokenCredential`.
- **Interactive credentials and the cache layout** (Windows, macOS,
  Linux): `dazure.DeviceCodeCredential` and
  `dazure.InteractiveBrowserCredential` sign in for real with the
  persisted cache; `get_refresh_token()` must find the token
  `azure-identity` wrote. This is the guard on the cache layout of
  §4.3.2.
- **Pasted-code sign-in**: from code-server, with a real app
  registration and a non-localhost redirect; a second `get_token()` is
  silent from the persisted cache; a tampered state is refused.
- **`ApiClient`**: one `fetch()` against ARM with `app_credential()` in
  `dev` and in `prod` with a real service principal.
- **`az` helpers**: `az_login()` device code, `az_account_show()`,
  `az_logout()`.
- **Spark**: one local PySpark read from a test storage account with
  the CLI refresh token, and with a service principal; the Hadoop
  version note of §12 for `WorkloadIdentityTokenProvider`.
- **DuckDB**: one read with `set_credential_secret()` and one with
  `set_sp_secret()`, account-scoped and unscoped.

## 9. Roadmap

The order of work is in [roadmap.md](roadmap.md).

## 10. Decisions

Settled by the maintainer in conversation on 2026-11-19:

- **D1.** Port only what the Python Azure SDK lacks; where it
  half-implements something, build on it and keep `dazure` small.
- **D2.** Name `dazure`: a `daz` prefix, not `dazazr`.
- **D3.** From `azr`: the API client, the Spark config with the
  `az login` refresh token, and the `az` CLI helpers.
- **D4.** From `quak`: its Azure parts.
- **D5.** The API client without `api_service` / `api_resource`.
- **D6.** The REST client is on `httpx`.
- **D7.** Coloured debug logging in `azr`'s style, request bodies
  included because they are what debugging needs. Existing tools were
  preferred, but `httpx` logs one plain line per call, so a small set of
  event hooks printing through `rich` provides it (§4.1).
- **D8.** Use the `azure-identity` credential classes directly, with a
  common way to get a refresh token from those that have one (§4.3).
- **D9.** No `az login` refresh-token path on Windows; Windows users use
  the interactive credentials or `$AZURE_REFRESH_TOKEN`.
- **D10.** Each API is an `ApiClient` subclass that controls its
  credentials: the developer's login (Azure CLI or device code) in
  development, a service principal in production whose client ID and
  secret variable names the class gives in full (no prefix), such as
  `APP_API_CLIENT_ID` and `APP_API_SECRET`. Managed and workload identity
  use the standard `AZURE_*` variables.
- **D21.** (2026-11-21) Do in Python exactly what
  `httr2::req_oauth_auth_code()` does with a non-localhost redirect URI
  and `cache_disk = TRUE`, since `azure-identity` cannot (§4.3.3).
- **D23.** (2026-11-21) Azure testing is mostly manual, in an
  environment with full Azure access; CI tests only what needs no Azure
  or a simple mock (§8).

The author's calls, open until the package repository records them:

- **D11.** From `quak`, only secrets and settings; lake operations and
  extension management stay out. Proposed to the maintainer, who did not
  object.
- **D12.** `rich` a required dependency, `duckdb` an extra, no PySpark
  dependency.
- **D13.** Repository `py-dazure`, Python >= 3.10, `py-dazdiff`'s
  tooling.
- **D14.** The refresh-token interface is a `get_refresh_token()`
  protocol returning `RefreshTokenInfo` (token, client ID, tenant,
  username), implemented by the `az login` reader,
  `RefreshTokenCredential` and thin subclasses of
  `InteractiveBrowserCredential` and `DeviceCodeCredential`.
- **D15.** `refresh_token_from_az_cli()` returns the CLI's current
  account, found from `azureProfile.json` without running `az`.
- **D16.** The interactive credentials read `azure-identity`'s persisted
  cache by rebuilding its `msal-extensions` persistence, guarded by a
  manual layout test (§8.2), rather than through the private `_cache`
  argument.
- **D22.** The pasted-code flow is a mode of
  `dazure.InteractiveBrowserCredential`, chosen by the redirect URI as
  httr2 chooses it, not a separate class, and it overrides only the
  parent's `_request_token()`, a private method guarded by the §8.1
  tests with MSAL patched and the §8.2 sign-in from code-server.
- **D17.** No implicit read of any cache by `spark_storage_conf()` or
  `RefreshTokenCredential`.
- **D18.** Spark defaults differ from `azr` where `azr` writes the CLI
  client ID for service-principal, managed and workload identity
  (§4.4).
- **D19.** Retry is a small loop of `dazure`'s own that follows `azr`:
  429, 503 and connection failures only, `azr`'s backoff; no 401
  replay.
- **D20.** `app_credential()`'s automatic mode: the named service
  principal when its client ID and secret variables are set, otherwise the
  developer's
  login; managed and workload identity only when asked for.

## 11. Open questions

1. Should `fetch()` paginate ARM-style `nextLink` responses? `azr`'s
   client does not; a generator method `fetch_pages()` could, at the cost
   of a second entry point.
2. Is an async client wanted? `httpx.AsyncClient` makes it cheap, but
   nothing in the motivating use needs it.
3. Should the pasted-code flow (§4.3.3) accept a client secret, as
   httr2's `oauth_client(secret = ...)` does, for apps whose redirect
   is registered as "Web"? It would need `msal.ConfidentialClientApplication`
   instead of the parent's public app, so it could not stay a subclass
   that overrides one method.
4. Should `set_credential_secret()` offer a refresh helper (a context
   manager that re-registers the secret before expiry) for long DuckDB
   sessions?

## 12. Sources and verification

- `azr` source as listed in the header. The Azure CLI client ID is
  `R/constants.R`; the Spark keys, endpoint and authority details are
  `R/spark-conf.R`; the defaults are `R/defaults.R`; the retry backoff is
  `backoff_default()` in `R/api-client.R`; the cache lookup is
  `find_msal_token()` in
  `R/credential-azure-cli.R`.
- `quak` source as listed. The secret SQL and scoping are `R/azure.R`;
  the tuning settings are `az_tune()` in `R/connection.R`.
- `httpx` 0.28.1, `httpx/_client.py`: the `httpx` logger logs
  `HTTP Request: %s %s "%s %d %s"` at `INFO` for every call;
  `HTTPTransport(retries=...)` retries connection failures only.
- `azure-identity` 1.27.0: `AzureCliCredential` runs only
  `az account get-access-token`; the package requires `msal>=1.39.0` and
  `msal-extensions>=1.2.0`.
- `msal` 1.39.0: `SerializableTokenCache`, `TokenCache.find()`,
  `ClientApplication.acquire_token_by_refresh_token()`.
- `azure-identity` 1.27.0, `_persistent_cache.py`: platform persistence
  and names (`.IdentityService`, `Microsoft.Developer.IdentityService`,
  `MSALCache`, `MsalClientID`); `_constants.py`:
  `DEVELOPER_SIGN_ON_CLIENT_ID` is the Azure CLI client ID, cache
  suffixes `.nocae` and `.cae`.
- `httr2` 1.3.0: `oauth_flow_auth_code()` (PKCE, state, localhost
  listener versus pasted code) and `oauth_flow_auth_code_read()` (the
  three reply forms). `azure-identity` 1.27.0, `_credentials/browser.py`:
  the redirect URI must have a port and is bound by
  `AuthCodeRedirectServer`; `_request_token()` is the only flow-specific
  method. `msal` 1.39.0: `initiate_auth_code_flow()`,
  `acquire_token_by_auth_code_flow()` and the reserved scopes.
- Not verified here and to be checked during stage 1: the Hadoop
  version note for `WorkloadIdentityTokenProvider` (taken from
  `azr`'s documentation, HADOOP-18610).
