# Manual checklist

What CI cannot check, because it needs real Azure: a real Entra sign-in,
the OS secret store `azure-identity` writes, a storage account, a service
principal (design §8, D23). This is the checklist of design §8.2, plus
every item an earlier stage deferred to it.

**When to run it.** Before every release, and whenever the floor or the
lock of `azure-identity` or `msal` moves: the private details items 2 and
3 guard (design §4.3.2, §4.3.3) are what a new release of either can
change. Items 2 and 3 run on Windows, macOS and Linux; the rest on at
least one OS each, as the table says. Record each run with the
[template](#record) in the release's pull request.

## How it is run

Two kinds of item:

- **Scripted** items are pytest modules here, `test_live_*.py`. They are
  skipped unless `DAZURE_LIVE=1`, so a plain `uv run pytest` reports them
  skipped (`tests/test_manual_checklist.py` checks that). With
  `DAZURE_LIVE=1`, a test whose environment variable is unset is skipped
  with the variable's name, so a partial run says what it left out.
- **Interactive** items need a person at a browser. `interactive.py` here
  drives each one and prints `PASS` or `FAIL` per step.

Neither prints a token or a secret: only lengths, client IDs, tenants and
usernames. Do not run them with `-s` plus extra debug logging of your own.

```sh
uv sync --all-extras                       # dazure, the dev group and duckdb
uv pip install pyspark                     # only for item 6
DAZURE_LIVE=1 uv run pytest tests/manual -ra -v
uv run python tests/manual/interactive.py --help
```

A skipped item is recorded as `not run`, never as a pass.

## Environment

| Item | OS | Needs |
| --- | --- | --- |
| 1. `az login` refresh token | macOS, Linux | `az` installed and logged in; a guest tenant for 1b |
| 2. Interactive credentials and the cache layout | Windows, macOS, Linux | a browser; on headless Linux, libsecret or `--unencrypted` |
| 3. Pasted-code sign-in | Linux (code-server) | an app registration (below) |
| 4. `ApiClient` against ARM | any | `az` logged in; the service principal |
| 5. `az` helpers | any | `az` installed; a clipboard tool (`pbcopy`, `clip`, `wl-copy`, `xclip` or `xsel`) |
| 6. Spark | macOS or Linux | PySpark, Java 17+, Maven Central reachable; the storage account; the service principal |
| 7. DuckDB | any | the `duckdb` extra; the storage account; the service principal |

Azure resources, created once:

- **A storage account** with hierarchical namespace (ADLS Gen2), a
  container, and one small test file in it, `.csv`, `.parquet` or
  `.json` (anything else is read as text lines). The signed-in user and
  the service principal both have *Storage Blob Data Reader* on the
  account.
- **A service principal** with a client secret, *Reader* on at least one
  subscription (for item 4) and the storage role above.
- **An Entra app registration** for item 3, a public client: under
  *Authentication*, a *Mobile and desktop applications* redirect URI that
  is **not** localhost, such as the code-server callback page
  `https://<code-server-host>/oauth/callback`. The page need not exist:
  the browser's address bar shows the callback URL to copy. Under *API
  permissions*, *Azure Service Management* → `user_impersonation`
  (delegated), consented.

Environment variables:

| Variable | Used by | Value |
| --- | --- | --- |
| `DAZURE_LIVE` | all scripted items | `1` to run them; anything else skips |
| `DAZURE_TEST_STORAGE_ACCOUNT` | 6, 7 | the storage account's short name |
| `DAZURE_TEST_CONTAINER` | 6, 7 | the container |
| `DAZURE_TEST_PATH` | 6, 7 | the test file's path in the container |
| `DAZURE_TEST_ROWS` | 6, 7 (optional) | the file's row count (data rows for CSV); without it, at least one |
| `DAZURE_TEST_TENANT_ID` | 4, 6, 7 | the service principal's tenant |
| `DAZURE_TEST_CLIENT_ID` | 4, 6, 7 | the service principal's client ID |
| `DAZURE_TEST_CLIENT_SECRET` | 4, 6, 7 | the service principal's secret |
| `DAZURE_TEST_GUEST_TENANT_ID` | 1b | a tenant the `az login` user is a guest in |
| `DAZURE_TEST_APP_CLIENT_ID` | 3 | the app registration's client ID |
| `DAZURE_TEST_APP_TENANT_ID` | 3 | its tenant |
| `DAZURE_TEST_REDIRECT_URI` | 3 | its non-localhost redirect URI, exactly as registered |
| `DAZURE_SPARK_PACKAGES` | 6 (optional) | the `hadoop-azure` coordinate; default `org.apache.hadoop:hadoop-azure:3.4.1` for PySpark 4, `3.3.4` for PySpark 3.5, matching the Hadoop PySpark bundles |

Keep the secret out of shell history (`read -s DAZURE_TEST_CLIENT_SECRET;
export DAZURE_TEST_CLIENT_SECRET`).

## 1. `az login` refresh token

Design §4.3.1. Deferred from Stage 1 (#4): a real `az login` and a real
redemption by Entra.

**1a. Home tenant.** After `az login`:

```sh
DAZURE_LIVE=1 uv run pytest tests/manual/test_live_az_cli.py -ra -v
```

Pass: `test_refresh_token_from_az_cli_is_redeemed` passes. It checks that
`refresh_token_from_az_cli()` returns the CLI's client ID and the tenant
and user `az account show` reports, that `RefreshTokenCredential` redeems
the token for an ARM access token whose `tid` is that tenant and whose
expiry is in the future, and that neither `repr` shows a token.

**1b. Guest tenant.** With `DAZURE_TEST_GUEST_TENANT_ID` set, the same run.
Pass: `test_refresh_token_from_az_cli_guest_tenant` passes (the redeemed
token's `tid` is the guest tenant).

**1c. Encrypted CLI cache (D24).** Optional, macOS or Linux, restores the
CLI afterwards:

```sh
az config set core.encrypt_token_cache=true && az login
uv run python -c "import dazure; dazure.refresh_token_from_az_cli()"
az config set core.encrypt_token_cache=false && az login
```

Pass: the second command raises `RefreshTokenNotFoundError` naming
`msal_token_cache.bin` and saying how to turn encryption off.

Record: pass/fail for 1a, 1b, 1c; the `az --version` line.

## 2. Interactive credentials and the cache layout

Design §4.3.2, D16. On **each of Windows, macOS and Linux**. Deferred from
Stage 3 (#6): real sign-ins, and the cache layout `azure-identity` really
writes on each OS. This is the guard on the private persistence layout
`get_refresh_token()` reads.

```sh
uv run python tests/manual/interactive.py device-code
uv run python tests/manual/interactive.py browser
```

On a headless Linux machine without a usable libsecret, add
`--unencrypted` (`allow_unencrypted_storage=True`, the plain file under
`~/.IdentityService/`), and record that you did.

Each run signs in for real, then checks, one `PASS` line each:

1. `get_refresh_token()` finds a token in the persisted cache, for the
   client ID and username of the sign-in's `AuthenticationRecord`;
2. the token is redacted in `repr`;
3. `RefreshTokenCredential` redeems it, for the record's tenant;
4. a second credential built with the record and
   `disable_automatic_authentication=True` gets a token silently from the
   persisted cache.

Pass: every step `PASS`, exit status 0. A `RefreshTokenNotFoundError` at
step 1 means the layout moved: compare `azure.identity._persistent_cache`
with design §4.3.2 before releasing.

Record: OS, pass/fail per credential, encrypted or `--unencrypted`, and on
Linux whether libsecret was used.

## 3. Pasted-code sign-in

Design §4.3.3, D22. From code-server (or any browser on another machine
than the Python process), with the app registration above. Deferred from
Stage 3 (#6): redeeming a real code from a callback page.

```sh
export DAZURE_TEST_APP_CLIENT_ID=... DAZURE_TEST_APP_TENANT_ID=...
export DAZURE_TEST_REDIRECT_URI=https://<code-server-host>/oauth/callback
uv run python tests/manual/interactive.py pasted-code
```

1. The script prints a URL and no browser opens. Open it, sign in, and
   copy the callback URL from the address bar (or the code the callback
   page shows); paste it at the prompt.
2. Pass: the same four `PASS` lines as item 2; the fourth is the silent
   second `get_token()` from the persisted cache.
3. **Tampered state.** Run it again, and before pasting change one
   character of the `state=` value in the callback URL. Pass: the run
   fails at sign-in with `ClientAuthenticationError` ("Authentication
   failed: ... state ..."), and no token is printed.
4. If the callback page shows the code alone, run once more and paste the
   code at the first prompt and the state at the second. Pass: as step 2.

Record: pass/fail for steps 2, 3, 4 (4 as `n/a` if the page gives the URL
only), the browser and the code-server host OS.

## 4. `ApiClient` against ARM

Design §4.1, §4.1.1. Deferred from Stage 5 (#8): a real `fetch()` in `dev`
and `prod`.

```sh
DAZURE_LIVE=1 uv run pytest tests/manual/test_live_api_client.py -ra -v
```

Pass: all three tests pass.

- `test_fetch_dev`: `app_credential(..., mode="dev")` is the
  `AzureCliCredential` → device-code chain, and `GET
  /subscriptions?api-version=2022-12-01` lists the CLI's current
  subscription.
- `test_fetch_prod`: `mode="prod"` with the service principal in the
  `DAZURE_TEST_*` variables is a `ClientSecretCredential`, and the same
  request returns a `value` list.
- Both run with `verbose=True` and check that the captured `dazure.http`
  log has the `>>> GET` record and contains neither the bearer token nor
  the client secret.
- `test_fetch_error_is_api_error`: an unknown subscription raises
  `ApiError` with ARM's 4xx status.

Also look once at the verbose output of a run with `-s`: the request and
response lines are readable, and no `Authorization` value appears.

Record: pass/fail per test.

## 5. `az` helpers

Design §4.2. Deferred from Stage 4 (#7): a real `az login`, `az account
show` and `az logout`, a real clipboard tool, and the device-code prompt
as the installed `az` streams it (Stage 4 checked its format in the
azure-cli source only). This logs the CLI out at the end.

```sh
DAZURE_LIVE=1 uv run pytest tests/manual/test_live_az_cli.py -ra -v -k account_show
uv run python tests/manual/interactive.py az-helpers
```

1. `test_az_is_login_and_account_show` passes (read-only: `az_is_login()`
   is true, `az_account_show()` gives the account and no token).
2. `az-helpers` runs `az_login(force=True)`. Pass: the device code and URL
   appear at once, before you sign in (streamed, not after `az` exits);
   pasting from the clipboard gives the same code; sign in.
3. Then one `PASS` line each: `az_account_show()` is the account
   `az_login()` returned, `az_is_login()` is true, after `az_logout()` it
   is false, and `az_account_show()` raises `AzCliNotLoggedInError`.
4. Run `az login` again before the other items.

Record: pass/fail for steps 1–3, the clipboard tool, `az --version`.

## 6. Spark

Design §4.4, §12. Deferred from Stage 2 (#5): a real Spark session against
ADLS with these keys. Also checks §12's Hadoop note, that
`WorkloadIdentityTokenProvider` needs Hadoop 3.4.1+.

```sh
uv pip install pyspark
DAZURE_LIVE=1 uv run pytest tests/manual/test_live_spark.py -ra -v
```

The tests skip, with the reason, if PySpark is not installed.

- `test_read_with_az_cli_refresh_token` (macOS, Linux):
  `spark_storage_conf(refresh_token=refresh_token_from_az_cli(),
  storage_account=...)` on a local session reads the test file.
- `test_read_with_service_principal`: `spark_storage_conf("client_secret",
  ...)` reads it.
- `test_workload_identity_provider_needs_hadoop_3_4_1`: the
  `hadoop-azure` jar is loaded, and `WorkloadIdentityTokenProvider` is
  present exactly when the Hadoop version is 3.4.1 or later. Run it once
  with PySpark 3.5 (Hadoop 3.3.4, absent) and once with PySpark 4 (Hadoop
  3.4.1, present) to check both sides of the note.

Pass: every test passes; the read count is `DAZURE_TEST_ROWS` when set.

Record: PySpark, Hadoop (in the JUnit property `hadoop_version`, or
`spark.sparkContext._jvm.org.apache.hadoop.util.VersionInfo.getVersion()`)
and Java versions, pass/fail per test.

## 7. DuckDB

Design §4.5. Deferred from Stage 6 (#9): real reads from ADLS,
account-scoped and unscoped.

```sh
DAZURE_LIVE=1 uv run pytest tests/manual/test_live_duckdb.py -ra -v
```

Each test opens a fresh in-memory connection, registers one secret and
reads the test file by its fully qualified URL,
`abfss://<account>.dfs.core.windows.net/<container>/<path>`.

- `test_read_with_credential_secret[scoped|unscoped]`:
  `set_credential_secret()` with
  `RefreshTokenCredential(refresh_token_from_az_cli())` (on Windows,
  `AzureCliCredential`), with and without `account`; the returned expiry
  is in the future.
- `test_read_with_sp_secret[scoped|unscoped]`: `set_sp_secret()` with the
  service principal, with and without `account`; `list_secrets()` does
  not show the client secret.

Pass: all four pass; the count is `DAZURE_TEST_ROWS` when set.

Record: DuckDB version, pass/fail per test.

## Record

Paste one block per OS into the release pull request:

```markdown
### Manual checklist — <OS>

- Date: YYYY-MM-DD
- OS: <name and version>; Python: <x.y.z>
- dazure: <version or commit>
- azure-identity: <x.y.z>; msal: <x.y.z>; msal-extensions: <x.y.z>; httpx: <x.y.z>; duckdb: <x.y.z>
- az: <version>; PySpark / Hadoop / Java: <x.y.z / x.y.z / x>

| Item | Result | Notes |
| --- | --- | --- |
| 1a `az login` refresh token, home tenant | pass / fail / not run | |
| 1b guest tenant | | |
| 1c encrypted CLI cache error | | |
| 2 `DeviceCodeCredential` + cache layout | | encrypted / --unencrypted |
| 2 `InteractiveBrowserCredential` + cache layout | | |
| 3 pasted code: sign-in and silent second token | | |
| 3 pasted code: tampered state refused | | |
| 3 pasted code: code then state | | |
| 4 `ApiClient` dev | | |
| 4 `ApiClient` prod | | |
| 4 `ApiError` on 4xx | | |
| 5 `az_is_login` / `az_account_show` | | |
| 5 `az_login` device code, clipboard, `az_logout` | | clipboard tool: |
| 6 Spark, refresh token | | |
| 6 Spark, service principal | | |
| 6 Hadoop note (`WorkloadIdentityTokenProvider` iff 3.4.1+) | | |
| 7 DuckDB credential secret, scoped / unscoped | | |
| 7 DuckDB SP secret, scoped / unscoped | | |
```

The versions come from:

```sh
uv run python -c "import sys, importlib.metadata as m; print(sys.version.split()[0], *(f'{p} {m.version(p)}' for p in ['dazure', 'azure-identity', 'msal', 'msal-extensions', 'httpx', 'duckdb']))"
```
