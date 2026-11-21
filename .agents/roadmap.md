# dazure (Python): roadmap

Status: draft 2026-11-21. Implements [design.md](design.md), whose §9
outline (0.0.1 to 0.0.4) these stages replace.
Target: v0.1.0, the first PyPI release.
Tracking: [v0.1.0 (#2)](https://github.com/pedrobtz/py-dazure/issues/2), with one
sub-issue per stage; [PyPI-release (#14)](https://github.com/pedrobtz/py-dazure/issues/14).

Adapted from the `pkg-roadmap` skill for R packages, as `py-dazdiff` did:
GitHub Actions running pytest replace r-actions, a PyPI release replaces
the CRAN submission, and there is no card on the R packages board. The
R assurance standard does not apply; each stage's **Tests.** list names
its oracles instead.

## Starting point

On `main` as of 2026-11-21 (`d5e33f1`): the package skeleton
(`pyproject.toml` with the design's dependencies and the `duckdb` extra,
`uv.lock`, ruff, one pytest test, CI with both profiles, `CLAUDE.md`,
`CHANGELOG.md`, MIT `LICENSE`) and the design with D23. No public API.
The full CI profile was green on the first push (15 jobs).

## CI policy

| Profile | Runs | Target |
| --- | --- | --- |
| `quick` | `ruff check`, `ruff format --check`, pytest on Ubuntu, Python 3.13, all extras | under 5 minutes |
| `full` | pytest on Ubuntu and Windows × Python 3.10–3.14, macOS × 3.10 and 3.14; lowest direct dependencies; build sdist and wheel, `twine check`, import the installed wheel | — |

Pull requests run `quick`; pushes to `main` and pull requests labelled
`full-ci` run `full`. A pull request's superseded runs are cancelled; a
push to `main` never is. A stage earns `full` only when the full set
checks something the stage introduces and later stages build on: in this
package, a branch on the operating system. Azure itself is never in CI
(design D23); what needs it is on the manual checklist of Stage 7.

## Stages

| Stage | Title | CI | Issue | Pull request | Done |
| --- | --- | --- | --- | --- | --- |
| 0 | [Package identity](#stage-0--package-identity) | quick | [#3](https://github.com/pedrobtz/py-dazure/issues/3) | `a095141` | 2026-11-21 |
| 1 | [Refresh tokens](#stage-1--refresh-tokens) | full | [#4](https://github.com/pedrobtz/py-dazure/issues/4) | [#16](https://github.com/pedrobtz/py-dazure/pull/16) | 2026-11-21 |
| 2 | [Spark config](#stage-2--spark-config) | quick | [#5](https://github.com/pedrobtz/py-dazure/issues/5) | | 2026-11-21 |
| 3 | [Interactive credentials](#stage-3--interactive-credentials) | full | [#6](https://github.com/pedrobtz/py-dazure/issues/6) | | |
| 4 | [az CLI helpers](#stage-4--az-cli-helpers) | full | [#7](https://github.com/pedrobtz/py-dazure/issues/7) | | |
| 5 | [REST client](#stage-5--rest-client) | quick | [#8](https://github.com/pedrobtz/py-dazure/issues/8) | | |
| 6 | [DuckDB](#stage-6--duckdb) | quick | [#9](https://github.com/pedrobtz/py-dazure/issues/9) | | |
| 7 | [Manual checklist](#stage-7--manual-checklist) | quick | [#10](https://github.com/pedrobtz/py-dazure/issues/10) | | |
| 8 | [Full CI](#stage-8--full-ci) | full | [#11](https://github.com/pedrobtz/py-dazure/issues/11) | | |
| 9 | [v0.1.0 readiness](#stage-9--v010-readiness) | full | [#12](https://github.com/pedrobtz/py-dazure/issues/12) | | |
| 10 | [Review](#stage-10--review) | full | [#13](https://github.com/pedrobtz/py-dazure/issues/13) | | |

## Stage 0 — Package identity

**Issue.** [#3](https://github.com/pedrobtz/py-dazure/issues/3), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `quick`.

**Goal.** The package installs, imports and is checked by CI on every
pull request. Done by the first commit, `a095141`, before this roadmap.

**Work.**

- `pyproject.toml` (hatchling; `azure-identity>=1.27`, `httpx>=0.28`,
  `rich>=13`; extra `duckdb`), `uv.lock`, ruff, pytest, `py.typed`.
- `.agents/`, `.github/`, `CLAUDE.md` excluded from the sdist.
- `.github/workflows/ci.yml` with both profiles, the `full-ci` label
  switch and the `concurrency` block.
- `CLAUDE.md`, `CHANGELOG.md`, `LICENSE`.

**Tests.**

- `__version__`: `importlib.metadata`, in `tests/test_package.py`.

**Exit criteria.**

- The full profile is green on `main` (run of `a095141`).
- `uv build` gives an sdist without `.agents/` or `.github/`.

**Design.** [§7](design.md#7-packaging).

## Stage 1 — Refresh tokens

**Issue.** [#4](https://github.com/pedrobtz/py-dazure/issues/4), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full — the az login reader branches on the OS (Windows refusal,
config directory, path handling), and every later stage takes its types.`

**Goal.** A refresh token can be found from `az login`, taken from
`$AZURE_REFRESH_TOKEN` or a string, and redeemed for access tokens, each
time carrying the client ID and tenant it belongs to.

**Work.**

- `dazure.errors`: `DazureError` and the subclasses the design names
  (`RefreshTokenNotFoundError`, `UnsupportedPlatformError`, ...).
- `RefreshTokenInfo` (redacted `repr`), `SupportsRefreshToken`,
  `AZURE_CLI_CLIENT_ID`, and the coercion of a string or
  `SupportsRefreshToken` with the §4.3.4 defaults.
- `refresh_token_from_az_cli()` (§4.3.1).
- `RefreshTokenCredential` (§4.3.5).
- A test helper that writes `azureProfile.json` and
  `msal_token_cache.json` through `msal.SerializableTokenCache.add()`
  from a fake token response, so the cache's schema comes from `msal`
  rather than from hand-written JSON.

**Tests.**

- Cache entry choice (no login, one account, work and guest accounts,
  one person in several tenants, a token for another client ID,
  `username` and `tenant_id` overrides, `$AZURE_CONFIG_DIR`): caches
  written by `msal` itself, in `tests/test_az_cli_token.py`.
- Refusals: missing profile, no default subscription, no matching token
  raise `RefreshTokenNotFoundError` naming the file and username; Windows
  raises `UnsupportedPlatformError`, on the real Windows leg; in
  `tests/test_az_cli_token.py`.
- String and environment defaults (`$AZURE_REFRESH_TOKEN`,
  `$AZURE_CLIENT_ID`, `$AZURE_TENANT_ID`, `"common"`): the §4.3.4 table,
  in `tests/test_refresh_token.py`.
- `RefreshTokenCredential`: `PublicClientApplication` patched at
  `acquire_token_by_refresh_token` (the whole class is replaced, since its
  constructor runs network discovery; D26, 2026-11-21); the scopes and token it was handed,
  the in-memory cache until five minutes before expiry, rotation
  returned by `get_refresh_token()`, an MSAL error becoming
  `ClientAuthenticationError`; in `tests/test_refresh_token_credential.py`.
- Secrets: a sentinel token never in `repr`, `str` or an error message
  of anything above, in `tests/test_secrets.py`.

**Exit criteria.**

- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The full profile is green on the pull request.

**Design.** [§4.3](design.md#43-refresh-tokens) (§4.3.1, §4.3.4,
§4.3.5), [§6](design.md#6-handling-secrets).

## Stage 2 — Spark config

**Issue.** [#5](https://github.com/pedrobtz/py-dazure/issues/5), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `quick`.

**Goal.** `spark_storage_conf()` reproduces `azr::azure_spark_storage_conf()`
key for key, and differs from it only where §4.4 says. With Stage 1 this
answers the package's motivating use.

**Work.**

- `tools/azr_spark_fixture.R`: loads a local `azr` checkout with
  `pkgload::load_all()`, runs every `auth_type` × `storage_account` (none,
  short, FQDN) × `authority_host` (public, US Gov, China) × `prefix`
  (default, `NULL`) with every argument explicit and placeholder secrets,
  and writes `tests/fixtures/azr_spark_conf.json` with the `azr` commit it
  ran against. Combinations `azr` refuses are recorded as expected
  errors. (2026-11-21: also two variants per type that `azr` normalises,
  an authority host given as a URL and a prefix with a trailing dot; 100
  cases from `azr` 0.3.7.9000 at `cca8ad5`.)
- `spark_storage_conf()` and `SparkStorageConf` (§4.4).

**Tests.**

- Explicit arguments: the `azr` fixture, exact dict equality per case,
  in `tests/test_spark_conf.py`.
- Defaults where `dazure` differs from `azr` (`client_secret`,
  `managed_identity`, `workload_identity`, a `SupportsRefreshToken`
  supplying its own IDs): the §4.4 list, in `tests/test_spark_conf.py`.
- Refusals: `shared_key` without `storage_account`, missing client or
  tenant IDs; in `tests/test_spark_conf.py`.
- `SparkStorageConf` redaction: sentinel secret, refresh token and
  account key absent from `repr` and `str`, present in the dict; in
  `tests/test_secrets.py`.

**Exit criteria.**

- The fixture is committed with its generator and the `azr` commit.
- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The quick profile is green on the pull request.

**Design.** [§4.4](design.md#44-spark_storage_conf).

## Stage 3 — Interactive credentials

**Issue.** [#6](https://github.com/pedrobtz/py-dazure/issues/6), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full — the persisted MSAL cache is built per OS (DPAPI, Keychain,
libsecret, plain file), so import and construction must hold on each leg.`

**Goal.** `dazure.DeviceCodeCredential` and
`dazure.InteractiveBrowserCredential` expose `get_refresh_token()`, and the
browser one signs in through a non-localhost callback page as httr2 does.

**Work.**

- Both subclasses with `TokenCachePersistenceOptions(name="dazure", ...)`
  and the read-only cache lookup of §4.3.2.
- The pasted-code flow of §4.3.3: the redirect rule, the
  `_request_token()` override, the reply parser.

**Tests.**

- Cache lookup: a plain-file `msal_extensions` persistence written by
  the test with `msal`'s cache, `.nocae` and `.cae`, entries for other
  accounts and client IDs; in `tests/test_interactive.py`.
- Reply parser: the three httr2 reply forms, an `error` query, garbage;
  the forms are copied from `httr2` 1.3.0's `oauth_flow_auth_code_read()`
  and its tests; in `tests/test_pasted_code.py`.
- Redirect rule: localhost or none reaches the parent unchanged; any
  other URI reaches the pasted flow; in `tests/test_pasted_code.py`.
- The flow with the MSAL app's `initiate_auth_code_flow()` and
  `acquire_token_by_auth_code_flow()` patched: the printed URL is the one
  MSAL built, the parsed reply and flow go back to MSAL, its
  `ValueError` becomes `ClientAuthenticationError`, no TTY raises
  `CredentialUnavailableError`; in `tests/test_pasted_code.py`.
- Construction and `get_refresh_token()` before sign-in on each OS leg,
  with `allow_unencrypted_storage=True`; in `tests/test_interactive.py`.

**Exit criteria.**

- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The full profile is green on the pull request.
- The real sign-ins and the cache-layout guard are on the Stage 7
  checklist, not here (D23).

**Design.** [§4.3.2](design.md#432-from-an-interactive-sign-in),
[§4.3.3](design.md#433-sign-in-through-a-callback-page-httr2s-pasted-code).

## Stage 4 — az CLI helpers

**Issue.** [#7](https://github.com/pedrobtz/py-dazure/issues/7), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full — subprocess and the fake az differ on Windows (az.cmd,
PATHEXT), so the Windows leg must run them.`

**Goal.** `az_account_show()`, `az_is_login()`, `az_login()` and
`az_logout()` work as §4.2 says, without a real `az`.

**Work.**

- The four helpers and their errors.
- `tests/fake_az/`: a Python script, launched by a shell stub on POSIX
  and an `az.cmd` on Windows, that records its arguments and plays back
  recorded outputs, including a device-code login that streams its
  prompt on stderr before finishing.

**Tests.**

- Arguments sent to `az` (`--output json`, `--only-show-errors`,
  `--tenant`, `--use-device-code`): the fake's own record, in
  `tests/test_az.py`.
- `az_login()`: already logged in returns without prompting unless
  `force`; the streamed device code is printed; no TTY raises
  `AzCliNonInteractiveError`; in `tests/test_az.py`.
- No `az` on `PATH`, not logged in, timeout: their errors, in
  `tests/test_az.py`.

**Exit criteria.**

- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The full profile is green on the pull request, Windows included.

**Design.** [§4.2](design.md#42-az-cli-helpers).

## Stage 5 — REST client

**Issue.** [#8](https://github.com/pedrobtz/py-dazure/issues/8), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `quick`.

**Goal.** `ApiClient` subclasses call an API with the credential their
class chooses, retry as `azr` does, parse by content type and log in
`azr`'s format.

**Work.**

- `BearerAuth`, `ApiClient`, `ApiError`, `app_credential()` (§4.1,
  §4.1.1), the logging hooks and `verbose`.
- A recording `httpx.MockTransport` that keeps every whole request
  (method, URL, headers, body) and serves scripted responses.

**Tests.**

- Path templating and encoding, missing and unused parameters: the
  recorded URL, in `tests/test_api_client.py`.
- Parsing by content type, empty body, `response_handler`, `ApiError`
  message: scripted responses, in `tests/test_api_client.py`.
- Retry: 429 and 503 and connection errors retried up to `max_tries`;
  500, 502, 504 and read timeouts sent once; `Retry-After` honoured;
  `azr`'s backoff bounds with a seeded or patched random and sleep; the
  recorded request count; in `tests/test_api_client.py`.
- Bearer token: fetched once, renewed five minutes before expiry,
  dropped after a 401; the recorded headers, in `tests/test_api_client.py`.
- `app_credential()`: every mode and partly set case, by credential type
  and constructor arguments; in `tests/test_app_credential.py`.
- Logging: the `>>>`/`<<<` records with `caplog`, no `Authorization`
  value anywhere, in `tests/test_api_client.py` and `tests/test_secrets.py`.

**Exit criteria.**

- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The quick profile is green on the pull request.

**Design.** [§4.1](design.md#41-apiclient).

## Stage 6 — DuckDB

**Issue.** [#9](https://github.com/pedrobtz/py-dazure/issues/9), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `quick`.

**Goal.** `dazure.duckdb` registers `quak`-compatible Azure secrets,
including one from any `TokenCredential`, and tunes the connection.

**Work.**

- The seven functions of §4.5, with `duckdb` imported lazily.
- CI caches DuckDB's extension directory keyed on the DuckDB version, so
  tests make no network call after the first run.

**Tests.**

- Each secret type, scoped and unscoped, names and scope prefixes:
  `duckdb_secrets()` of a real in-memory DuckDB, in `tests/test_duckdb.py`.
- Quoting: values with quotes and backslashes round-trip through
  `duckdb_secrets()`, in `tests/test_duckdb.py`.
- `set_credential_secret()` with a fake `TokenCredential`: the token
  registered and `expires_on` returned, in `tests/test_duckdb.py`.
- `tune()` and `azure_settings()`: `duckdb_settings()`, in
  `tests/test_duckdb.py`.
- `import dazure` without `duckdb` installed: the lowest-dependencies job
  without the extra, in CI.

**Exit criteria.**

- Every **Tests.** line exists, compares with the named oracle, and was
  seen to fail.
- The quick profile is green on the pull request.

**Design.** [§4.5](design.md#45-duckdb-secrets-and-tuning).

## Stage 7 — Manual checklist

**Issue.** [#10](https://github.com/pedrobtz/py-dazure/issues/10), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `quick`.

**Goal.** Everything §8.2 checks by hand can be run from one checklist in
an environment with full Azure access.

**Work.**

- `tests/manual/README.md`: the §8.2 items, the environment each needs
  (OS, app registration, storage account, service principal), and the
  record to paste into a release pull request.
- `tests/manual/test_live_*.py`, skipped unless `DAZURE_LIVE=1`, for the
  items a script can drive; the rest are steps to follow.

**Tests.**

- The live tests are collected and skipped without `DAZURE_LIVE`: the
  pytest summary in CI.

**Exit criteria.**

- The checklist covers every §8.2 item.
- The quick profile is green on the pull request. Running the
  checklist is part of Stage 9, by the maintainer.

**Design.** [§8.2](design.md#82-manual-an-environment-with-full-azure-access).

## Stage 8 — Full CI

**Issue.** [#11](https://github.com/pedrobtz/py-dazure/issues/11), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full` (always).

**Goal.** The full profile is green on everything Stages 1 to 7 built.

**Work.**

- Run the full profile on `main`'s code and fix what it finds; add a
  coverage job with a floor at the level reached, less a point.

**Tests.**

- Nothing new beyond the fixes, each with the test that shows it.

**Exit criteria.**

- A full-profile run green on the pull request and on the merge commit.

## Stage 9 — v0.1.0 readiness

**Issue.** [#12](https://github.com/pedrobtz/py-dazure/issues/12), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full` (always).

**Goal.** The package is ready to publish, short of the review.

**Work.**

- Version `0.1.0`, the `CHANGELOG.md` heading, the README in
  `py-dazdiff`'s style.
- `.github/workflows/release.yml` with trusted publishing to TestPyPI on
  dispatch and PyPI on a `v*` tag, as `py-dazdiff`'s.
- The maintainer runs the Stage 7 checklist on Windows, macOS and Linux
  and records it in the pull request.

**Tests.**

- `twine check --strict` and an installed-wheel import: the `package`
  job.

**Exit criteria.**

- A full-profile run green on the merge commit.
- The manual checklist recorded in the pull request.

## Stage 10 — Review

**Issue.** [#13](https://github.com/pedrobtz/py-dazure/issues/13), sub-issue of
[v0.1.0](https://github.com/pedrobtz/py-dazure/issues/2).

**CI.** `full` (always).

**Goal.** The release candidate is reviewed and its findings fixed.

**Work.**

- A critical review of code, tests and style; blocking and required
  findings become sub-issues of the Review issue and are fixed together.
- A packaging review: metadata, sdist and wheel contents, the README on
  PyPI, the TestPyPI upload installing cleanly.

**Exit criteria.**

- Every blocking and required review issue closed, `CHANGELOG.md`
  reflecting any user-visible fix, and a full-profile run green on
  `main`, whose head becomes the release commit.

## After 0.1.0

- [§11](design.md#11-open-questions) Q1 to Q4 (pagination, an async
  client, a confidential client for the pasted-code flow, a DuckDB
  refresh helper): none is needed for the motivating use, and none
  blocks a stage.

## Blocking open questions

None. The Hadoop version note of [§12](design.md#12-sources-and-verification)
is checked by hand in Stage 7's checklist.
