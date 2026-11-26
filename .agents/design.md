# RFC 0078: `dazapiz`, the Azure helpers azure-identity lacks

Adopted from [RFC 0078](https://github.com/pedrobtz/packages/blob/c2a33fa70cbfe8a2b6d79c4fc70d036caf682d56/rfcs/not-started/0078-dazure-azure-helpers-for-python.md)
on 2026-11-21. This file is the single source of truth for the design; the
RFC is now a pointer here. Changed since adoption: §8 split into automated
and manual tiers (D23), with §4.3.2, §7, §9, D16 and D22 following;
§9's outline moved to [roadmap.md](roadmap.md) on 2026-11-21;
§4.3.1, §4.3.4 and §4.3.5 detailed by Stage 1 (D24 to D26), 2026-11-21;
§4.1 and §4.1.1 detailed by Stage 5 (D36 to D43), 2026-11-21;
§4.5 detailed by Stage 6 (D44 to D48), 2026-11-21;
§4.1's logged bodies abbreviated as `azr`'s (D43 replaced, §11 Q5
answered; #22), 2026-11-21;
§4.1 `fetch(parse=...)` and model bodies, §5 `ResponseParseError` and the
Petstore example, §7 and §8 type checking, real-HTTP tests and the Petstore
item (D49 to D58; #26), 2026-11-21;
§7 documentation site (#27), 2026-11-21;
renamed `dazure` to `dazapiz` (D61), 2026-11-26;
§4.1, §4.1.1, §4.2 and §4.3.1 changed by the Stage 10 review (D62 to D67;
#36 to #49), 2026-11-26.

- **Status:** Proposed. The decisions in §10 marked "maintainer" were
  settled in conversation on 2026-11-19 (D21 on 2026-11-21); the rest
  are the author's calls and stay open until the package repository
  records them.
- **Date:** 2026-11-19.
- **Package:** `dazapiz`, a Python package (repository `pedrobtz/py-dazapiz`,
  import name `dazapiz`). This is the portfolio's first Python RFC; it
  follows `py-dazdiff`'s layout (`pyproject.toml` with hatchling, `uv`,
  ruff, pytest, Python >= 3.10). `dazapiz` is free on PyPI and there is no
  `pedrobtz/py-dazapiz` or `pedrobtz/dazapiz` repository, both checked on
  2026-11-26. Proposed and first built as `dazure` (`pedrobtz/py-dazure`);
  renamed on 2026-11-26 (D61). `dependencies = ["azure-identity>=1.27", "httpx>=0.28",
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

## 1. What dazapiz is

`dazapiz` brings to Python the parts of `azr` and `quak` that the Azure
SDK for Python does not already provide, and nothing else. It is a thin
layer: wherever `azure-identity` or `msal` already does a job,
`dazapiz` calls it rather than reimplementing it. The REST client is on
`httpx`; `azure-core` is used only for the `TokenCredential` and
`AccessToken` types.

```python
from dazapiz import az_login, spark_storage_conf, refresh_token_from_az_cli

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
already solves this in R (`azure_spark_storage_conf()`); `dazapiz` brings
it to PySpark users.

### 1.1 What dazapiz is not

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
it comes from, what Python already has, and what `dazapiz` adds.

1. **Spark / Hadoop ABFS config.** From
   `azr::azure_spark_storage_conf()`. Python has nothing. `dazapiz` adds
   the whole builder (§4.4).
2. **Refresh token from `az login`.** From `azr`'s `find_msal_token()`
   (same result, different lookup; §4.3)
   and `default_refresh_token()`. `msal.SerializableTokenCache` reads the
   cache file and `msal-extensions` decrypts it. `dazapiz` adds locating
   the cache and choosing the entry (§4.3).
3. **`RefreshTokenCredential`.** From `azr::RefreshTokenCredential`.
   `msal.PublicClientApplication.acquire_token_by_refresh_token()` does
   the exchange. `dazapiz` adds a `TokenCredential` wrapper (§4.3).
4. **A refresh-token interface.** `azr`'s credentials return an httr2
   token that carries `refresh_token`. `azure-identity` keeps refresh
   tokens private: `TokenCredential` returns access tokens only.
   `dazapiz` adds a `get_refresh_token()` protocol and thin subclasses of
   `InteractiveBrowserCredential` and `DeviceCodeCredential` that
   implement it (§4.3). The browser subclass also adds httr2's
   pasted-code sign-in for a redirect URI that is not on localhost,
   which `azure-identity` cannot do (§4.3.3).
5. **REST client.** From `azr::api_client`. `httpx` is the HTTP layer
   and logs each call on the `httpx` logger; `azure-identity` supplies
   tokens. `dazapiz` adds the bearer `httpx.Auth`, retry with backoff,
   `fetch()` with path templates and content-type parsing, the
   coloured request/response logging, and per-API credentials: a
   subclass picks the developer's login or a service principal from its
   own environment variables (§4.1).
6. **`az` CLI helpers.** From `azr::az_cli_login()` and its siblings.
   `AzureCliCredential` runs `az account get-access-token` only. `dazapiz`
   adds login, logout, is-logged-in and account show (§4.2).
7. **DuckDB Azure secrets and tuning.** From `quak::az_set_*_secret()`,
   `az_list_secrets()`, `az_conn_settings()` and `az_tune()`. The
   `azure` extension exists; secrets are raw SQL. `dazapiz` adds typed
   helpers, per-account scoping and secrets from any `TokenCredential`
   (§4.5).

## 3. Design principles

1. **The SDK first.** Anything `azure-identity` or `msal` does is used,
   not redone. A `dazapiz` function that wraps one says so
   in its docstring.
2. **Any `TokenCredential` works.** Wherever a credential is taken, the
   type is `azure.core.credentials.TokenCredential`, so
   `DefaultAzureCredential()` and `dazapiz.RefreshTokenCredential` are
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
   `dazapiz`. DuckDB is an extra, imported lazily.

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
        transport: httpx.BaseTransport | None = None,  # D60: for tests
        sleep: Callable[[float], None] | None = None,  # D60: retry waits
    ): ...

    @property
    def credential(self) -> TokenCredential | None: ...  # D60: the one chosen

    def fetch(
        self,
        path: str,                         # "/subscriptions/{subscription_id}"
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,   # override parsing
        parse: Callable[[Any], T] | None = None,  # D49: typed result
        **path_params: str,
    ) -> T | Any: ...                      # overloads: T with parse, Any without

    def close(self) -> None: ...           # also a context manager
    def __enter__(self: C) -> C: ...       # the subclass's own type
```

The client holds one `httpx.Client(base_url=host_url,
timeout=httpx.Timeout(timeout, connect=connect_timeout),
transport=transport)`; `transport=None` is httpx's own. The retry loop
waits with `sleep` (default `time.sleep`). `credential` is the
read-only credential the client uses, `None` when unauthenticated. These
three are the public test hooks (D60): a test passes an
`httpx.MockTransport` and `sleep=waits.append`, and checks the type of
`client.credential` to see which credential an environment selects.

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
  3. `ManagedIdentityCredential()`, with `client_id=$AZURE_CLIENT_ID`
     when that is set (2026-11-21, below).

  Workload and managed identity read the standard `AZURE_*` variables
  through `azure-identity` itself (maintainer): the named variables are
  for the service principal only. A client ID without a secret, or the
  reverse, is an error naming the missing variable, never a silent
  fall-through; so is both set with no tenant.
  `prod` never uses a developer login.
- **`dev`**: `ChainedTokenCredential(AzureCliCredential(),
  azure.identity.DeviceCodeCredential())`, the device code tried only in an
  interactive session (a TTY or a notebook kernel), so a batch job fails
  instead of waiting for a prompt. The device code has no persisted cache,
  so it prompts where no secret store is usable (D64).
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
and credential class (never a value) are logged on the `dazapiz.http`
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
(URL-encoded; a missing or unused parameter, or a placeholder with a
conversion or format spec, is a `ValueError`), refuses a `path` that is
an absolute URL (D66), leaves `None` query values out, sends the request
and parses the body by content type: JSON (`application/json`,
`text/json`, any `+json`) to Python objects, XML (`application/xml`,
`text/xml`, any `+xml`) to `xml.etree.ElementTree.Element`, anything
else to `str`, an empty body to `None`. The result then goes
through `response_handler`. `azr`'s default handler converts data frames
to `data.table`; the Python default is the identity. A non-2xx response
after retries raises `dazapiz.ApiError`, an `httpx.HTTPStatusError`
subclass whose message carries the method, URL, status and response
body.

**Logging.** `httpx`'s own logging is one plain `INFO` line per call
on the `httpx` logger, `HTTP Request: GET <url> "HTTP/1.1 200 OK"`, with
no request body, no timing, no size, no error body and no colour; its
`httpcore` `DEBUG` records are transport noise. That is not what `azr`
shows, so `dazapiz` adds `httpx` event hooks (about 30 lines, prototyped
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
pretty-printed and abbreviated as `azr`'s `format_json_body()` (D43); the
response hook logs status, elapsed time and size (green on success) and,
on failure, the response body (red, a JSON one abbreviated too); the retry
loop logs its waits (yellow). Timing is taken with `time.perf_counter()`
stored in `request.extensions` by the request hook, because
`response.elapsed` raises inside a response hook until the response is
closed (found by the prototype).

The hooks write to a `dazapiz.http` logger, so the records can be routed
or silenced like any other. `verbose=True` turns them on and, if the
logger has no handler yet, attaches a `rich.logging.RichHandler(markup=False,
show_time=False, show_level=False, show_path=False)` that colours each
record by its `dazapiz_style` (D63), which prints the
lines above with `rich`'s colours and JSON highlighting. The `httpx`
logger is left alone so its line does not duplicate `>>>`. The hooks
never log headers, so the bearer token cannot appear; bodies are logged
as sent, abbreviated but not redacted, so a caller posting secrets in a
body should leave `verbose` off.

Details settled in Stage 5 (2026-11-21):

- `app_credential()`'s mode also takes the azure-identity class names that
  `AZURE_TOKEN_CREDENTIALS` takes for the five credentials (D36);
  `EnvironmentCredential` means the named service principal, as in `azr`.
  Any other value, and the names of credentials `dazapiz` does not build
  (`AzurePowerShellCredential`, `InteractiveBrowserCredential`, ...),
  raise `ValueError`. Surrounding spaces are ignored.
- A partly set service principal raises `ValueError` naming the missing
  variable in every mode that reads it, automatic included (D37); so does
  an unknown mode (D39). An empty variable counts as unset (D25).
- `dev` asks `_session.is_interactive()` when the credential is built:
  outside a TTY or kernel the chain is `ChainedTokenCredential(AzureCliCredential())`
  alone (D38). The single name `device_code` is built wherever asked for.
- The log line is `ℹ Credential: <class>, mode <mode> (<source>).`, the
  source `from mode`, `from AZURE_TOKEN_CREDENTIALS` or `automatic`; a
  chain lists its members' classes.
- `ManagedIdentityCredential` (in `prod` and as `managed_identity`) gets
  `client_id=$AZURE_CLIENT_ID` when that is set, else none (system-assigned;
  empty is unset, D25), as `DefaultAzureCredential` passes
  `managed_identity_client_id`. azure-identity 1.27.0's class does not
  read the variable itself (`_credentials/managed_identity.py`); this
  follows D10's "the standard `AZURE_*` variables" (coordinator,
  2026-11-21).
- Retried connection failures are `httpx.ConnectError` and
  `httpx.ConnectTimeout`, where the request cannot have reached the
  server (D40). After the last attempt the `httpx` exception is raised
  as is; a 429 or 503 after the last attempt raises `ApiError`.
  `Retry-After` is delay-seconds or an HTTP date, not capped (httr2 does
  not cap it); an invalid one, `inf` and `NaN` included, falls back to the
  backoff, and an HTTP date with no zone (`-0000`) is UTC (#41). The warning's
  attempt number is the attempt that failed, as httr2 passes it to
  `azr`'s backoff.
- `ApiError`'s message is `<METHOD> <URL> failed: HTTP <status> <reason>`,
  then the response body on the next line when there is one.
- An empty body returns `None` without calling `response_handler`, as
  `azr` returns before its handler (D41). The media type is the
  content type before any `;`, lower-cased.
- Logging: the `>>>` and `<<<` records are `INFO`, failures too; the retry
  warning is `WARNING` and logged whether or not `verbose` is set, as
  `azr`'s alert is. Messages are plain text; the colour (green, red,
  yellow) travels as the record's `dazapiz_style`, which only dazapiz's
  own handler reads, so any other handler prints the text as sent (D63,
  replacing D42). The size is the body's bytes / 1024 with two decimals; the time
  three significant digits. `verbose=True` also lowers the logger's level
  to `INFO` when its effective level is higher.
- JSON bodies (request, and failed response) are logged abbreviated as
  `azr`'s `format_json_body()` with its defaults (D43; maintainer,
  2026-11-21): an object or array of more than 10 items keeps the first
  and last 5, a nested array of scalars (an R atomic vector) of more than
  12 keeps the first and last 6, with a bare `...` between; a top-level
  array counts as a list of 10, as `azr`'s `lapply()` makes it one. The
  layout is jsonlite's `pretty = TRUE`: two-space indent, a nested array
  of scalars on one line, anything else one item per line. A body that
  does not parse as JSON, or is not JSON, is logged as is, in full.
  `azr` prints a failed response body verbatim; issue #22 asks for both,
  so `dazapiz` abbreviates that one too.
- Checked against `tools/azr_json_body_fixture.R`'s output
  (`tests/fixtures/azr_json_body.json`, azr `cca8ad5`): structure (which
  items are kept, where `...` goes) and text match `azr` exactly, except
  for these jsonlite quirks, not copied because they change what the body
  says (2026-11-21):
  - In a truncated or mixed-type nested array of scalars, R coerces the
    vector to character, so `azr` prints `["1", ..., "13"]`, `"TRUE"`,
    and `"NA"` for a null among numbers; `dazapiz` keeps the JSON types.
    The test unquotes those tokens in `azr`'s text for exactly those four
    cases, whose inputs hold no such strings.
  - jsonlite unboxes a one-element array (`{"x": [5]}` prints `"x": 5`;
    `[[1], [2]]` prints `[1, 2]`) and boxes a top-level scalar (`5`
    prints `[5]`, `null` prints `[]`); `dazapiz` prints the value as sent.
  - Numbers are Python's `json` text (`1e10` is `10000000000.0`,
    `1.23456789` stays), not jsonlite's 4 significant digits.
  - `azr` turns any `"..."` string in the body into a bare `...`; in
    `dazapiz` only the placeholder is bare.
- The tests send through a recording `httpx.MockTransport` passed as
  `transport=` and record waits with `sleep=` (D60); they patch only the
  module's `_uniform`, `_now` and `_clock`.

**Typed results: `parse=`** (D49, maintainer, 2026-11-21; #26). `parse` is
any callable `Any -> T`: `Model.model_validate`,
`TypeAdapter(list[Model]).validate_python`, or a function. It is applied to
the body as content-type parsing left it (the `content_type` override
included), and when given it replaces `response_handler` for that call.
Two `@overload`s type `fetch()`: with `parse` it returns `T`, without it
`Any`, as before. `parse` is a keyword, so `{parse}` cannot be a path
placeholder (as `query`, `json` and the others cannot).

- An empty 2xx body reaches `parse` as `None` (D50), unlike
  `response_handler`, which an empty body skips (D41). A non-2xx response
  raises `ApiError` before `parse` is called; a retried response is not
  parsed.
- An `Exception` from `parse` raises `ResponseParseError` (§5) `from` it
  (D54): `"<METHOD> <URL>: the response body was rejected by parse=
  (<exception type>)."`. So does a body whose media type (the
  `content_type` override, else the response's) is JSON or XML but which
  does not parse: `"... the response body is not valid application/json
  (JSONDecodeError)."`, before `response_handler` or `parse` sees it
  (D57). The message never carries the body or a header,
  because pydantic's message quotes the input it rejected; that detail
  stays on `__cause__`. `request` and `response` are the `httpx` objects.

**Model bodies: `json=`** (D49). A pydantic v2 model is sent as
`model_dump(mode="json", by_alias=True, exclude_unset=True)`, a dataclass
instance field by field as `dataclasses.asdict()` does, anything else as
before (D52). Models and dataclasses are converted wherever they sit: at
the top, in lists and tuples (sent as lists), in dict values and in
dataclass fields; dict keys are left alone (D58). The
check is duck-typed (a non-class with a callable `model_dump`), so
`dazapiz` neither imports nor depends on pydantic. `mode="json"` makes
dates, URLs and enums JSON values; `by_alias` sends the wire names;
`exclude_unset` leaves out the fields the caller did not set, but keeps a
field explicitly set to `None` (D51). The conversion happens before httpx
encodes the body, so the verbose log shows the body as sent.

**Example.** `examples/petstore.py` (repository only, D53) is a
`PetStoreClient(ApiClient)` for the Swagger Petstore v3 with pydantic
models for every request and response, run as
`uv run python examples/petstore.py`:

- one base, `ConfigDict(alias_generator=to_camel, validate_by_name=True,
  validate_by_alias=True, frozen=True)` (pydantic 2.11's names); request
  models `extra="forbid"`, response models `extra="ignore"`;
- `PetCreate` / `Pet` and `OrderCreate` / `Order`, the response models
  with a required `id`; `Category` and `Tag` shared, so they ignore
  extras; `Literal` statuses; ids `Annotated[int, Field(ge=0, le=2**63 -
  1)]` (int64); request photo URLs `HttpUrl`, response ones `str` as the
  schema has them;
- `TypeAdapter(list[Pet])` built once at module level;
- typed methods `add_pet`, `get_pet`, `find_pets_by_status`,
  `update_pet`, `delete_pet`, `place_order`, `get_order` (and
  `delete_order`, for the demo to clean up), NumPy-style docstrings;
  a 404 from `get_pet` / `get_order` raises `PetNotFoundError` /
  `OrderNotFoundError`, chained to the `ApiError`;
- `main()`, guarded by `if __name__ == "__main__":`, uses the client as a
  context manager against the public store.

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
none by default, and its `timeout` covers its `az account show` checks
too, D67) and runs `az` with `--only-show-errors`.

Getting tokens from the CLI is not wrapped: that is
`azure.identity.AzureCliCredential`.

Details settled in Stage 4 (2026-11-21):

- The errors share a base, `AzCliError(DazapizError)`; `AzCliNotFoundError`,
  `AzCliNotLoggedInError`, `AzCliNonInteractiveError` and
  `AzCliTimeoutError` (also a `TimeoutError`) derive from it.
  `az_login()` and `az_logout()` raise on a non-zero exit (D31).
- A failing `az` is "not logged in" when its stderr says `az login`
  (`az account show`: "Please run 'az login' to setup account.") or
  "no active accounts" (`az logout`); any other failure is `AzCliError`
  with `az`'s stderr in the message.
- `az_is_login()` is `False` on any `AzCliError` (D32).
- `az_login()` checks the existing login before the TTY, as `azr` does,
  so a reused login works in a batch job. The tenant comparison ignores
  case, and a domain matches the account's `tenantDefaultDomain` (D67). A `tenant_id` must match `[A-Za-z0-9.-]+`, as in §4.4.
- The device code is found by `azr`'s pattern `enter the code
  ([A-Z0-9]+) to authenticate` on each stderr line, ANSI styling removed;
  the URL is the first `https://` in that line, else
  `https://microsoft.com/devicelogin`. `az` prints MSAL's message with
  `print()`, not its logger, so `--only-show-errors` keeps it
  (azure-cli `auth/identity.py`, checked 2026-11-21).
- `az_login()` returns the default account of `az login`'s list (D33)
  and prints only the code, the URL, the clipboard notice and the account
  name.
- No browser is opened, and there is no `use_bridge` or `verbose`
  (D34).
- A timeout kills the whole process tree (D35).

### 4.3 Refresh tokens

`azr` gives one interface across its credentials: `get_token()` returns
an httr2 token, and for the user flows that token carries
`refresh_token`. In Python the shared interface is
`azure.core.credentials.TokenCredential`, which every `azure-identity`
class implements, and `dazapiz` takes it wherever an access token is
needed (principle 2). But `azure-identity` deliberately exposes no
refresh token: `AccessToken` / `AccessTokenInfo` hold the access token,
expiry and refresh time only, and the interactive credentials keep their
refresh tokens in a private MSAL cache. `dazapiz` therefore adds one
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

`spark_storage_conf()` and `RefreshTokenCredential` accept a plain
string or any `SupportsRefreshToken`, and the DuckDB helper takes one
through `RefreshTokenCredential` (D47, 2026-11-21), so the token always
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
that token in the cache to its `home_account_id`; `dazapiz` reaches the
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

Details settled in Stage 1 (2026-11-21):

- Usernames match case-insensitively, as `msal`'s `get_accounts()` does;
  accounts and refresh tokens are matched on `home_account_id` and
  `environment`; with several CLI refresh tokens for the account (one per
  scope set), the newest `last_modification_time` wins.
- One username can be several cache accounts: the same name in two
  clouds, or two home accounts (D62, 2026-11-26). Among the `Account`
  entries with that username, those whose `environment` is a sign-in
  host of the subscription's `environmentName` (`AzureCloud`,
  `AzureChinaCloud`, `AzureUSGovernment`, `AzureGermanCloud`, with
  Entra's aliases) are preferred, then those whose `realm` is the
  profile's tenant (msal writes one `Account` entry per tenant signed
  in to). A preference no entry meets is dropped, not enforced, so
  `tenant_id` for a tenant the CLI never signed in to still finds the
  token. Where the profile cannot tell the accounts apart (both
  overrides given, a custom cloud, a tenant none of them signed in to),
  the newest token wins, as before.
- `username` alone takes the tenant of that user's subscription (the
  default one if it is theirs); `username` and `tenant_id` together do
  not read the profile at all.
- `azureProfile.json` is read as `utf-8-sig`: the Azure CLI writes it
  with a byte order mark.
- An encrypted cache is not read (D24). With
  `core.encrypt_token_cache=true` the CLI writes `msal_token_cache.bin`
  through `msal-extensions` (Keychain, libsecret) instead of the JSON
  file; `azr` reads only the JSON file and has no answer either. When
  only the `.bin` exists, the error says so and how to switch back.

macOS and Linux only (maintainer). On Windows the CLI signs in through
the Windows broker by default and the function raises
`UnsupportedPlatformError` pointing to §4.3.2 and to
`$AZURE_REFRESH_TOKEN`. The cache file is only read, never written:
`azr::write_msal_token()` is not ported.

#### 4.3.2 From an interactive sign-in

`dazapiz.InteractiveBrowserCredential` and `dazapiz.DeviceCodeCredential`
subclass the `azure-identity` classes of the same name and add
`get_refresh_token()`. They are the Python counterparts of `azr`'s
`AuthCodeCredential` and `DeviceCodeCredential`, and they work on every
platform, Windows included.

- Constructed with `cache_persistence_options=
  TokenCachePersistenceOptions(name="dazapiz",
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
  `_persistent_cache._get_persistence()` (file name `dazapiz.nocae`,
  Keychain service `Microsoft.Developer.IdentityService`, libsecret
  attribute `MsalClientID`). That layout is `azure-identity`'s
  implementation detail, not a documented API, so a manual test signs
  in for real on each OS with the installed `azure-identity` and reads
  the token back (§8.2); it is rerun whenever `azure-identity` moves.
  The private argument `_cache`, which would avoid the persisted store,
  is not used.

Details settled in Stage 3 (2026-11-21):

- The layout matches azure-identity 1.27.0 as described:
  `_persistent_cache._get_persistence(allow_unencrypted, account_name,
  cache_name)`, called by `_load_persistent_cache()` with account
  `MSALCache` and cache name `<name>.nocae` / `<name>.cae` (the Keychain
  account is the cache name); `MsalCredential._get_app(**kwargs)`;
  `InteractiveCredential._request_token(*scopes, **kwargs)`.
- The lookup calls that private `_get_persistence()` itself, with the
  arguments `_load_persistent_cache()` passes, instead of copying its
  four platform branches (D30); a test compares the two calls. It only
  `load()`s each persistence: no `PersistedTokenCache`, no lock file, no
  write.
- Both constructors take `allow_unencrypted_storage: bool = False`, the
  parent's default; it builds the `"dazapiz"` options and is refused
  together with the caller's own `cache_persistence_options` (D29).
- Selection matches `home_account_id` and `client_id` only, as the
  parent's silent lookup matches the account, not the environment; of
  several tokens, across both caches, the newest
  `last_modification_time` wins, as in §4.3.1. None found raises
  `RefreshTokenNotFoundError` naming the cache and the username.
- With `authentication_record=` given, `get_refresh_token()` does not
  sign in; the record says whose token to read.

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

`dazapiz.InteractiveBrowserCredential` therefore follows httr2's rule:

- **Localhost redirect, or none.** Unchanged `azure-identity`
  behaviour: a local listener and the system browser.
- **Any other redirect URI.** The redirect URI is kept by `dazapiz`
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

Details settled in Stage 3 (2026-11-21):

- "Localhost" is httr2's set, `localhost` and `127.0.0.1`
  (`normalize_redirect_uri()`); a localhost URI without a port gets the
  parent's `ValueError`, as before.
- The prompts are httr2's ("Enter authorization code or URL: ", "Enter
  state parameter: "), read with `input()` and trimmed. The authorize
  URL is printed to stdout; no browser is opened, since in a hosted
  session it would open on the wrong machine.
- A reply starting `http://` or `https://` is a callback URL, and its
  whole query goes to MSAL, as the parent's listener passes it. A reply
  that base64-decodes (standard or URL-safe) to a JSON *object* is the
  JSON form; jsonlite's one-element arrays are unwrapped. Anything else
  is a bare code, and the state is asked for.
- An `error` in the callback URL raises `ClientAuthenticationError` with
  `error` and `error_description`, as httr2's listener does. An empty
  reply, a reply without a code, or without a state, raises
  `ClientAuthenticationError` before MSAL is called. Closed input
  (`EOFError`) raises `CredentialUnavailableError`.
- The interactive check is `dazapiz._session.is_interactive()`:
  `sys.stdin.isatty()`, or an already imported IPython whose shell has a
  `kernel`. §4.1.1 and §4.2 are to use the same check.

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
hard-code three things, and `dazapiz` takes all three as arguments:

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
  address bar, which is the first reply form. `dazapiz` ships no page.

Tenant (GUID, domain, `organizations` or `common`), scopes and
`authority_host` (sovereign clouds) are the parent's arguments
unchanged.

```python
from dazapiz import InteractiveBrowserCredential

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
`"common"`, as in `azr`. An empty variable counts as unset, where
`azr`'s `Sys.getenv()` would pass the empty string on (D25). Nothing
given and no `$AZURE_REFRESH_TOKEN` raises `RefreshTokenNotFoundError`.
Nothing reads a cache implicitly: callers pass
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

The `msal` application is built on the first `get_token()`, one per
tenant, because its constructor runs instance and tenant discovery over
the network (D26). `get_token(tenant_id=...)` asks that tenant instead
of the token's own; `claims` goes to Entra as the `claims` parameter and
bypasses the in-memory token. The margin is inclusive: a token with 300
seconds or fewer left is renewed. An MSAL error dict becomes
`ClientAuthenticationError` with its `error` and `error_description`,
and the refresh token, should Entra ever echo it, replaced by
`<redacted>`. `authority_host` defaults to `$AZURE_AUTHORITY_HOST`, then
the public cloud, as `azure-identity` does.

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
    authority_host: str | None = None,   # $AZURE_AUTHORITY_HOST, else the public cloud
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

`client_id` and `tenant_id`, when passed, win over a
`SupportsRefreshToken`'s own (D28). Arguments another `auth_type` uses
are accepted and ignored, as in `azr`. Missing `client_secret`
(`$AZURE_CLIENT_SECRET`), `token_file` (`$AZURE_FEDERATED_TOKEN_FILE`) or
`account_key` is a `ValueError`, as `azr` refuses them; a missing refresh
token is `RefreshTokenNotFoundError` (§4.3.4).

Found while porting, 2026-11-21 (Stage 2), checked against the `azr`
fixture or `azr`'s source:

- `authority_host` may be given as a URL: a trailing `/` and then an
  `http(s)://` scheme are stripped, in that order, before it is used, as
  `azr`'s `normalize_authority_host()` does. The fixture has variants for
  it.
- A trailing `.` in `prefix` is dropped (`"spark.hadoop."` gives the same
  keys as `"spark.hadoop"`), as in `azr`.
- `azr` checks the tenant against `^[A-Za-z0-9.-]+$` only where it builds
  a token URL (`client_secret`, `refresh_token`); `dazapiz` checks it for
  every type that uses one, since Hadoop concatenates `msi.tenant` into a
  URL too. Reason: a tenant with `/` builds a wrong URL silently.
- An empty string passed for any argument is a `ValueError`, where `azr`
  would write it out; an empty environment variable counts as unset (D25).
  Reason: an empty ID or key only fails later, inside an executor.
- `shared_key` without `storage_account` is refused by `azr` too, so the
  fixture records those six cases as expected errors.

A refresh token used with the wrong client ID fails only later, inside
a Spark executor with a Hadoop-shaped error; returning the client ID
with the token is what prevents that.

`SparkStorageConf` is a `dict[str, str]` subclass whose `__repr__` and
`__str__` replace the values of `*.oauth2.client.secret`,
`*.oauth2.refresh.token` and `*.key` with `"<redacted>"`; the dict
itself holds the real values so it can be passed to
`SparkSession.builder.config(map=...)` or `spark.conf.set`.
The property is matched with or without an account suffix, and the
`oauth2.refresh.token.endpoint` key, which starts like the refresh token,
is told apart by its `https://` value, so an account named `endpoint`
still has its token redacted; `copy()` and `|` keep the class
(2026-11-21, Stage 2). `workload_identity` notes in its docstring that it needs Hadoop 3.4.1+
(Spark 4.x, Databricks 14.3+ LTS, Synapse 3.4+), as `azr` documents.

### 4.5 DuckDB secrets and tuning

In `dazapiz.duckdb`, needing the `duckdb` extra. Each helper takes a
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

Secrets are named `dazapiz_default` or `dazapiz_<account>` (non-
alphanumerics to `_`), so that `quak`'s and `dazapiz`'s secrets never
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

Details settled in Stage 6 (2026-11-21), checked against DuckDB 1.1.0,
1.5.6 and 2.0.1 with the azure extension:

- The extension is installed only if `duckdb_extensions()` says it is
  not, and loaded only if it is not loaded.
- Values are DuckDB string literals, single quotes doubled, because 1.1
  cannot bind parameters in `CREATE SECRET` (D45). A value with a NUL
  character is refused, since 1.1 ends the literal there. `SET` binds its
  value.
- The secret name is lower-cased (D44). `access_token` gets no
  `ACCOUNT_NAME`, as in `quak`, although DuckDB 2 would take one.
- `list_secrets()` and `azure_settings()` return a `DuckDBPyRelation`
  (D46). Each helper logs one INFO record on `dazapiz.duckdb` naming the
  secret, where `quak` prints with `cli`.
- `set_credential_secret()` takes a `TokenCredential` only, and raises
  `TypeError` pointing to `RefreshTokenCredential` for anything without
  `get_token()` (D47).
- Bad arguments raise `ValueError` or `TypeError`; a failed statement
  raises DuckDB's own error type (D48). `tune()` warns, as `quak` does,
  when the buffer size is not a multiple of the chunk size.

## 5. Public API summary

```python
from dazapiz import (
    ApiClient, app_credential,
    az_login, az_logout, az_is_login, az_account_show,
    RefreshTokenInfo, SupportsRefreshToken, AZURE_CLI_CLIENT_ID,
    refresh_token_from_az_cli, RefreshTokenCredential,
    InteractiveBrowserCredential, DeviceCodeCredential,
    spark_storage_conf, SparkStorageConf,
)
from dazapiz.duckdb import (
    set_token_secret, set_credential_secret, set_sp_secret, set_chain_secret,
    list_secrets, azure_settings, tune, STORAGE_SCOPE,
)
from dazapiz.testing import StaticTokenCredential
```

`ApiClient(..., transport=, sleep=)` and its read-only `credential`
property are its test hooks (§4.1, D60).

`dazapiz.testing` (D59) holds test doubles for code built on dazapiz, with
no dependency beyond azure-core: `StaticTokenCredential(token="fake-token",
*, expires_in=3600)` implements `TokenCredential` and `SupportsTokenInfo`,
returns the token with a fresh expiry on every call, records each call's
scopes in `.calls`, and redacts the token in `repr` (§6). It is exported
from `dazapiz.testing` only, so `import dazapiz` does not offer a fake
credential next to the real ones. The guide page "Testing your API
client" shows it with `respx` on an `ApiClient` subclass.

Errors derive from `dazapiz.DazapizError`; `dazapiz.ApiError` also derives
from `httpx.HTTPStatusError`. `dazapiz.ResponseParseError` is what
`fetch(..., parse=...)` raises when `parse` fails on a successful response
(§4.1, D54); it is not an `ApiError`, since the request succeeded.
`ClientAuthenticationError` from a credential passes through unwrapped.

`examples/petstore.py` (§4.1) shows an `ApiClient` subclass with pydantic
models, and `examples/azure_petstore.py` the same client with an Entra ID
scope and service-principal variables, tested offline in `examples/tests/`;
they are in the repository, not the package.
Names are snake_case Python names; `azr`'s `az_cli_` prefix is shortened
to `az_` because the module already says Azure.

## 6. Handling secrets

- No token, key or secret that `dazapiz` handles appears in `repr`,
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

Repository `pedrobtz/py-dazapiz`, laid out like `py-dazdiff`: `src/dazapiz/`,
`tests/`, `pyproject.toml` (hatchling), `uv.lock`, `CHANGELOG.md`,
`ruff` with the same rule set, typed (`py.typed`) and type-checked by
pyright in strict mode (D55). `examples/`, `typings/` and the Petstore
fixture and its tests are repository-only: left out of the sdist, never in
the wheel. Python 3.10 to 3.14,
matching `azure-identity`'s floor. CI on Ubuntu, macOS and Windows,
for the platform branches (`UnsupportedPlatformError` on Windows, the
config and cache paths); the real persisted cache of §4.3.2 is checked
by hand on each OS (§8.2). Published
to PyPI by a release workflow with trusted publishing, as `py-dazdiff`
does.

Documentation site built with great-docs (Quarto) from `great-docs.yml`,
`user_guide/` and the NumPy docstrings, deployed to GitHub Pages
(`https://pedrobtz.github.io/py-dazapiz/`) by `.github/workflows/docs.yml`
on pushes to `main`, and built and linted (`great-docs lint`) on every
pull request; great-docs 0.17.0 and Quarto 1.11.9 pinned, as `py-dazdiff`
does. The reference groups follow §5; `dazapiz.duckdb` (and `dazapiz.testing`) is listed by
submodule-qualified names (`duckdb.tune`) and read by static analysis
(`dynamic: false`), since `import dazapiz` does not import it. Guide code
is never executed (it needs Azure); the Petstore walkthrough and the testing page include
`examples/` code by line range, checked by a test. `great-docs.yml`
and `user_guide/` are left out of the sdist (decided 2026-11-21, #27: the
maintainer asked for the site as `py-dazdiff` has it).

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
  where `dazapiz` deliberately differs from `azr` (§4.4), have their own
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
  `Authorization` value in captured log records, `ApiError` body. Logged
  JSON bodies against a fixture of `azr`'s `format_json_body()` output,
  generated by `tools/azr_json_body_fixture.R` (§4.1). `parse=` and model
  bodies against the bytes the recording transport received
  (`tests/test_fetch_typed.py`).
- **`ApiClient` over real HTTP** (D56). `pytest-httpbin` serves httpbin on
  loopback, so `tests/test_api_client_httpbin.py` sees what arrived: the
  bearer token on `/bearer` (and a 401 without a credential), path
  parameters percent-encoded on the request line (the server's own log;
  httpbin's echo decodes `%2F`), query and JSON bodies on `/anything`,
  parsing of `/json`, `/xml`, `/html` and `/status/204`, 429 and 503
  retried (counted from the retry warnings, `sleep=` recording the waits) and
  500 not, `/delay/2` under a 0.5 s timeout sent once, and timing and size
  in the log records with no `Authorization` value.
- **The Petstore example** (D53). `tests/test_petstore_example.py`, with
  Petstore-shaped responses on the recording transport: each method's
  method, path, query and body as recorded; responses missing `name`,
  `id` or `photoUrls`, with an unknown status or a negative id raise
  `ResponseParseError`; an unknown field is ignored; an invalid
  `PetCreate` or `OrderCreate` fails at construction and nothing is sent;
  a 404 is the domain error with the `ApiError` as `__cause__`. The spec
  oracle is the store's OpenAPI document, committed as
  `tests/fixtures/petstore-openapi.json` (Apache-2.0, provenance in
  `petstore-openapi.md`): every model's aliases are its schema's property
  names, its required fields the schema's `required` plus the listed
  deliberate additions, the status `Literal`s the schema's `enum`s, and
  every property `example` validates and dumps back unchanged.
- **Testing an `ApiClient` subclass** (D59). `examples/tests/` is the
  pattern the guide page "Testing your API client" includes: `respx` for
  HTTP (an unmocked request raises), `StaticTokenCredential` as
  `credential=`, and an autouse fixture calling `pytest-socket`'s
  `disable_socket(allow_unix_socket=True)` for that directory only (the
  httpbin and DuckDB tests in `tests/` keep their sockets). It checks a
  validated result with the bearer token and the class's scope, the JSON
  body as recorded, a malformed body, a 404 domain error, 503 retried and
  500 not, `app_credential()`'s choice by environment checked by type with
  sockets blocked (building `ClientSecretCredential` and the `dev` chain
  opens no connection), and that both guards fire. `tests/test_testing.py`
  covers the credential itself. The retry tests pass `sleep=`, and the
  mode tests check `client.credential` (D60). `examples/` is on pytest's `pythonpath`
  and pyright's `extraPaths`, so every test imports the example modules by
  name.
- **Types.** pyright (strict, Python 3.10) runs in the lint job over
  `src/`, `examples/` and `tests/typing/` (D55), whose `assert_type`
  checks pin `fetch()`'s overloads and `__enter__`'s return type; pytest
  runs the same file against a mock transport.
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
item where one helps, skipped by pytest unless `DAZAPIZ_LIVE=1`. Run
before every release and whenever the `azure-identity` or `msal` floor
or lock moves, because the private details these items guard (§4.3.2,
§4.3.3) are what a new release can change. Each run is recorded with
date, OS and versions in the release's pull request.

The checklist (2026-11-21, Stage 7) has the scripted items as
`tests/manual/test_live_*.py` (items 1, 4, 6, 7 and the read-only part of
5), skipped by a collection hook in `tests/manual/conftest.py` unless
`DAZAPIZ_LIVE` is exactly `1`, configured only by `DAZAPIZ_TEST_*`
variables, and skipped naming the variable when one is unset. The
interactive items (2, 3, `az_login()` / `az_logout()`) are driven by
`tests/manual/interactive.py`, which a person runs. It also carries the
items the stages deferred to it: the encrypted CLI cache error (D24), a
real clipboard tool and the streamed device code of `az login`, and the
pasted code given as code then state. The §12 Hadoop note is checked by
loading `hadoop-azure` and looking for `WorkloadIdentityTokenProvider`.

- **`az login` refresh token** (macOS, Linux): `refresh_token_from_az_cli()`
  after a real `az login`, including a guest tenant; the token is
  redeemed by `RefreshTokenCredential`.
- **Interactive credentials and the cache layout** (Windows, macOS,
  Linux): `dazapiz.DeviceCodeCredential` and
  `dazapiz.InteractiveBrowserCredential` sign in for real with the
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
- **Petstore example** (optional, no Azure; D56): the example's pet and
  order lifecycle against the public store, skipped unless
  `DAZAPIZ_LIVE_HTTP=1` (`DAZAPIZ_LIVE` does not turn it on).

## 9. Roadmap

The order of work is in [roadmap.md](roadmap.md).

## 10. Decisions

Settled by the maintainer in conversation on 2026-11-19:

- **D1.** Port only what the Python Azure SDK lacks; where it
  half-implements something, build on it and keep `dazapiz` small.
- **D2.** Name `dazapiz`: a `daz` prefix, not `dazazr`.
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

Settled in Stage 1 (2026-11-21), the implementer's calls:

- **D24.** `refresh_token_from_az_cli()` does not read the CLI's
  encrypted `msal_token_cache.bin`; it names it in the error. Reason:
  decrypting needs the OS secret store, which D23 keeps out of CI, and
  the encryption is off by default outside Windows, which D9 excludes.
- **D25.** An empty `$AZURE_REFRESH_TOKEN`, `$AZURE_CLIENT_ID` or
  `$AZURE_TENANT_ID` counts as unset. Reason: an empty client ID or
  tenant can only fail later with a less clear error.
- **D26.** `RefreshTokenCredential` builds its `msal`
  `PublicClientApplication` lazily, per tenant. Reason: the constructor
  does network discovery, which must not happen at construction (Spark
  driver) nor in tests (D23), so the tests replace the class rather than
  one method.

Settled in Stage 2 (2026-11-21), the implementer's calls:

- **D27.** `spark_storage_conf(authority_host=None)` reads
  `$AZURE_AUTHORITY_HOST`, else the public cloud, as `azr`'s
  `default_azure_host()` and `RefreshTokenCredential` do. Reason: the
  signature's literal default could not honour the variable its comment
  named.
- **D28.** Explicit `client_id` and `tenant_id` win over those a
  `SupportsRefreshToken` supplies. Reason: §4.4's defaults apply "when not
  passed", and an explicit argument is what the fixture compares.

Settled in Stage 3 (2026-11-21), the implementer's calls:

- **D29.** The interactive credentials take
  `allow_unencrypted_storage: bool = False`. Reason: §4.3.2 left the
  value open, and the parent's default keeps the refresh token encrypted
  unless the caller opts out.
- **D30.** The cache lookup calls azure-identity's private
  `_get_persistence()` rather than rebuilding each platform's
  persistence by hand. Reason: one private call, checked by a test
  against `_load_persistent_cache()`, follows azure-identity's layout
  where a copy of its branches would drift.

Settled in Stage 4 (2026-11-21), the implementer's calls:

- **D31.** `az_login()` and `az_logout()` raise `AzCliError` on a
  non-zero exit, where `azr` returns the exit status or warns. Reason: a
  failed login must not come back looking like a result.
- **D32.** `az_is_login()` returns `False` on any `AzCliError`, no `az`
  and a timeout included, as `azr::az_cli_is_login()`. Reason: it answers
  "can I use the CLI login now"; `az_account_show()` says why not.
- **D33.** `az_login()` returns the `isDefault` entry of `az login`'s
  list, else its first, else `az_account_show()`. Reason: §4.2 promises
  one account `dict`, and that entry is what `az account show` shows next.
- **D34.** `az_login()` prints the code and URL and opens no browser; the
  clipboard is the first of `pbcopy`, `clip`, `wl-copy`, `xclip`, `xsel`
  that works, silently skipped otherwise. Reason: §4.2 names printing and
  the clipboard only, `azr`'s browser opening fails silently on remote
  hosts, and `clipr` runs the same tools.
- **D35.** A timeout kills `az`'s process tree (a new session on POSIX,
  `taskkill /T` on Windows). Reason: `az` is a script that starts Python,
  and killing the script alone leaves its child holding the pipes.

Settled in Stage 5 (2026-11-21), the implementer's calls:

- **D36.** `app_credential()` accepts azure-identity's class names as well
  as its own. Reason: `AZURE_TOKEN_CREDENTIALS` is shared with
  `DefaultAzureCredential`, so a value valid there must not break a client.
- **D37.** In automatic mode a client ID without its secret, or the
  reverse, is an error, not `dev`. Reason: a half-configured deployment
  silently using a developer login is the fall-through `prod` forbids.
- **D38.** `dev` decides on the device code when the credential is built.
  Reason: §4.1 makes the choice in `__init__`, from the session as it is.
- **D39.** `app_credential()`'s configuration errors are `ValueError`.
  Reason: they are bad input, as a missing path parameter is, and
  azure-identity's constructors raise the same.
- **D40.** Only `ConnectError` and `ConnectTimeout` are retried among
  transport errors. Reason: they alone guarantee the server never saw the
  request, which is §4.1's rule for resending a `POST`.
- **D41.** An empty body skips `response_handler`. Reason: `azr` returns
  `NULL` before its handler, and a handler need not accept `None`.
- **D42.** (Replaced by D63, 2026-11-26.) Log records carry `rich` markup, with bodies and URLs escaped.
  Reason: §4.1's `RichHandler(markup=True)` colours from the message, and
  unescaped `[...]` in a body would be read as markup.
- **D43.** Logged JSON bodies, request and failed response, are
  abbreviated as `azr`'s `format_json_body()` (§4.1), replacing "logged
  whole". Reason (maintainer, 2026-11-21): azr abbreviates; bodies
  abbreviated as format_json_body() (#22).

Settled in Stage 6 (2026-11-21), the implementer's calls:

- **D44.** DuckDB secret names are lower-cased. Reason: DuckDB 1.1 folds
  an unquoted name to lower case and 2.x keeps it, so only a lower-case
  name is the same on every supported version.
- **D45.** Values in `CREATE SECRET` are quoted literals, never bound.
  Reason: the 1.1 floor's parser refuses `?` and `$name` there, and one
  quoting path tested on every version beats two.
- **D46.** `list_secrets()` and `azure_settings()` return a DuckDB
  relation. Reason: it is DuckDB's own table, printed like `quak`'s tibble
  and converted by `.df()` or `.pl()`, without making pandas a dependency.
- **D47.** `set_credential_secret()` takes a `TokenCredential` only; a
  refresh token goes through `RefreshTokenCredential`. Reason: §4.5's
  signature and example say so, and §4.3's wording that the DuckDB helpers
  take a refresh token directly is corrected to match.
- **D48.** A failed `CREATE SECRET` re-raises DuckDB's error type with any
  secret value replaced by `<redacted>` and the original unchained;
  `tune()` prefixes the setting's name. Reason: DuckDB errors can quote the
  statement (§6), and callers keep catching `duckdb.Error`.

Settled for #26 (2026-11-21):

- **D49.** `fetch(..., parse=...)` returns a typed result, `json=` takes
  pydantic models and dataclasses, and `examples/petstore.py` shows a
  Petstore client with pydantic models for bodies and responses. Reason
  (maintainer, 2026-11-21): typed bodies and responses for `ApiClient`,
  with validation enforced both ways, the example to "implement the
  current best practices" (#26).
- **D50.** An empty 2xx body is passed to `parse` as `None`, where it
  skips `response_handler` (D41). Reason: the overload promises `T`;
  skipping `parse` would return `None` typed as the model, the hole the
  maintainer's validation is meant to close. A caller expecting an empty
  body gives no `parse`, or one that accepts `None`.
- **D51.** Models are dumped with `exclude_unset=True`, not
  `exclude_none=True`. Reason: unset optional fields stay off the wire (no
  `null` the API did not ask for), while a field the caller set to `None`
  is sent, so an API that clears a field on `null` can still be told to;
  `exclude_none` cannot express that.
- **D52.** A model is anything that is not a class and has a callable
  `model_dump`; a dataclass is `dataclasses.is_dataclass()` of a
  non-class. Reason: `dazapiz` does not depend on pydantic (#26).
  (Converting the top-level value only was replaced by D58.)
- **D53.** The Petstore example's models differ from a literal reading of
  the schema where the real store does: `PetCreate` and `OrderCreate`
  take an optional `id` (the public store, 1.0.27, answers 500 to a pet
  without one, probed 2026-11-21); `Pet.photo_urls` is `list[str]` as the
  schema types it (no `format: uri`; the store holds pets whose URL is
  `"string"`), while `PetCreate` checks `HttpUrl`; the response models
  require `id`, `OrderCreate` requires `petId` and `quantity` (at least
  1); `find_pets_by_status()` sends one request per distinct status,
  because the store's `status` parameter takes one value (a repeated one
  is ignored, a comma list refused). Reason: an example of best practice
  validates against the API's contract and works against the real server.
- **D54.** `ResponseParseError` derives from `DazapizError` only, carries
  `request` and `response`, and wraps any `Exception` from `parse` (not
  `BaseException`). Reason: the HTTP exchange succeeded, so it is not an
  `httpx.HTTPStatusError`; keeping the response lets a caller look at
  what was rejected without the message quoting it.
- **D55.** pyright strict (Python 3.10) over `src/`, `examples/` and
  `tests/typing/`, configured in `[tool.pyright]`. `msal` and
  `msal_extensions` ship no types, so `typings/` holds partial stubs of
  the names `dazapiz` uses (type checking only, not packaged); the only
  ignores are on azure-identity's private API (`_persistent_cache`, D16;
  `_request_token`, D22), each with its reason. Runtime checks of
  arguments an untyped caller could get wrong stay, written so strict
  mode does not call them unnecessary. Strict mode also made the
  `azureProfile.json` reader treat a user name or tenant that is not a
  string, or a profile that is not an object, as no default subscription
  (`RefreshTokenNotFoundError`) instead of passing it on. Reason: the maintainer asked for
  typing enforced in CI, and silencing whole rules would enforce nothing.
- **D56.** Real-HTTP tests use `pytest-httpbin` on loopback in every CI
  leg; the Petstore live test is a separate opt-in, `DAZAPIZ_LIVE_HTTP=1`.
  Reason: httpbin is local, so CI stays offline (D23); the public store
  is shared and on the internet, so it is never in CI, and needing no
  Azure it should not need `DAZAPIZ_LIVE`.
- **D57.** A JSON or XML body that does not parse (`ValueError`, which
  covers `JSONDecodeError` and a body that is not UTF-8, or
  `ET.ParseError`) raises `ResponseParseError` from the parser's error,
  with the same message rules as D54. Reason (coordinator, 2026-11-21, on
  #28): the caller asked for parsed content and the exchange succeeded,
  so it is the same failure as a `parse` that rejects the body, and the
  parser's own message can quote the body. The Petstore example still
  reads its `DELETE` reply with `content_type="text/plain"`: the store
  labels the text `Pet deleted` as JSON.
- **D58.** `json=` converts models and dataclass instances recursively,
  in lists, tuples, dict values and dataclass fields, with D51's dump
  options; dict keys are never converted. Reason (coordinator,
  2026-11-21, on #28): a list of models is a common body, and a model
  inside a dataclass would otherwise be deep-copied, not dumped. Keys
  stay as given: a converted key would be an unhashable dict, and JSON
  keys are strings anyway.
- **D59.** (maintainer, 2026-11-21: testing guide; StaticTokenCredential
  public) A guide page on testing an `ApiClient` subclass in CI, with the
  Petstore treated as Azure-hosted, and `dazapiz.testing.StaticTokenCredential`
  public so users need not write their own fake credential. The example
  tests run fully offline: `respx` for HTTP, `pytest-socket` for the rest
  (maintainer's addition). Reason: the maintainer asked how to mock a
  client for a real Azure API in CI (#30); a public fake keeps users off
  dazapiz's internals, and blocking sockets proves no test leaks to Entra
  ID or the API.
- **D60.** (maintainer, 2026-11-21: follow-up to the approved testing
  guide, D59) `ApiClient.__init__` takes keyword-only `transport`
  (passed to `httpx.Client`) and `sleep` (the retry loop's wait, default
  `time.sleep`), and `ApiClient.credential` is a read-only property for
  the credential chosen. They replace the private `_transport()` and
  `_sleep` that dazapiz's tests patched. Reason: a user-facing guide must
  not patch private names; these are the smallest public hooks for a
  mock transport, instant retries and checking `app_credential()`'s
  choice.
- **D61.** (maintainer, 2026-11-26) The package, import name and
  repository are renamed from `dazure` / `py-dazure` to `dazapiz` /
  `py-dazapiz`, with every derived name following: `DazapizError`,
  the `DAZAPIZ_*` environment variables, the `dazapiz.*` loggers and the
  `dazapiz_default` token cache. No aliases: nothing was published under
  the old name. Reason: the maintainer chose the new name.
- **D62.** (2026-11-26, #47) `refresh_token_from_az_cli()` prefers the
  cache accounts in the profile's cloud and signed in to its tenant
  before newest-wins (§4.3.1). Reason: matching on username alone gave
  the same UPN in another cloud, or another home account, whichever
  token was newer.
- **D63.** (2026-11-26, #42) Log records carry no `rich` markup; the
  colour is the record's `dazapiz_style`, applied by the handler
  `verbose=True` attaches (`markup=False`), and bodies and URLs are not
  escaped. Replaces D42. Reason: the retry warning is logged without
  `verbose`, and the `>>>`/`<<<` records whenever the logger is at
  `INFO`, so any other handler printed the tags, or the escapes, as text.
- **D64.** (maintainer, 2026-11-26, #39) `dev` mode's device code is
  `azure.identity.DeviceCodeCredential()` with no persisted cache, not
  `dazapiz.DeviceCodeCredential()`. Mode `device_code` keeps dazapiz's.
  Reason: dazapiz's encrypted cache cannot open without a secret store
  (headless Linux: SSH, devcontainers, Codespaces, WSL), so the chain
  failed before showing a code; with no authentication record a new
  process prompted anyway, so the cache bought nothing there.
- **D65.** (2026-11-26, #44) A value of `AZURE_TOKEN_CREDENTIALS` that
  `DefaultAzureCredential` takes but dazapiz does not build
  (`AzureDeveloperCliCredential`, `AzurePowerShellCredential`,
  `VisualStudioCodeCredential`, `InteractiveBrowserCredential`) means
  automatic mode, with a warning; the same name as `mode=` is still an
  error. Reason: D36's own, a value valid there must not break a client;
  an argument is the caller's explicit choice.
- **D66.** (2026-11-26, #36, #40, #43, #45) `fetch()` refuses an absolute
  URL as `path` and a placeholder with a conversion or format spec,
  drops `None` query values (as httr2's `req_url_query()` drops `NULL`),
  and parses `text/json`, `+json`, `text/xml` and `+xml` as JSON or XML.
  Reason: httpx ignores `base_url` for an absolute URL while the bearer
  token is still added, so a `nextLink` could send it off-host; the rest
  sent values or parsed bodies other than the caller meant. MSAL's
  warning about the pasted flow's `response_mode="query"` is silenced
  around that one call, since the mode is the flow's.
- **D67.** (2026-11-26, #37, #38) `az_login(timeout=...)` is one deadline
  for every `az` it runs, the `az account show` checks included, and a
  `tenant_id` domain matches `tenantDefaultDomain`. Reason: the checks
  used `az_account_show()`'s fixed 10 s even with `timeout=None`, and
  `tenantId` is always a GUID, so a domain never matched an existing
  login.

The author's calls, open until the package repository records them:

- **D11.** From `quak`, only secrets and settings; lake operations and
  extension management stay out. Proposed to the maintainer, who did not
  object.
- **D12.** `rich` a required dependency, `duckdb` an extra, no PySpark
  dependency.
- **D13.** Repository `py-dazapiz`, Python >= 3.10, `py-dazdiff`'s
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
  `dazapiz.InteractiveBrowserCredential`, chosen by the redirect URI as
  httr2 chooses it, not a separate class, and it overrides only the
  parent's `_request_token()`, a private method guarded by the §8.1
  tests with MSAL patched and the §8.2 sign-in from code-server.
- **D17.** No implicit read of any cache by `spark_storage_conf()` or
  `RefreshTokenCredential`.
- **D18.** Spark defaults differ from `azr` where `azr` writes the CLI
  client ID for service-principal, managed and workload identity
  (§4.4).
- **D19.** Retry is a small loop of `dazapiz`'s own that follows `azr`:
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
5. Answered 2026-11-21 (#22): verbose logs abbreviate JSON bodies as
   `azr`'s `format_json_body()` does (D43).

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
- Not verified here: the Hadoop version note for
  `WorkloadIdentityTokenProvider` (taken from `azr`'s documentation,
  HADOOP-18610). It is checked by hand, item 6 of the manual checklist
  (`test_workload_identity_provider_needs_hadoop_3_4_1`), against
  PySpark 3.5 and 4 (2026-11-21, Stage 7).
