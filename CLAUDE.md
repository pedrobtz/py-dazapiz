# dazure (Python)

The Azure helpers `azure-identity` lacks: the `az login` refresh token
carried into Spark's ABFS configuration, a small `httpx` REST client,
`az` CLI helpers and DuckDB Azure secrets. Ported from the R packages
`azr` and `quak`, keeping only what the Python Azure SDK does not
already do.

## Where things are decided

- `.agents/design.md` is the single source of truth for what the package
  is and why: API, behaviour, divergences from `azr`, decisions, open
  questions. Adopted from RFC 0078 in `pedrobtz/packages` on 2026-11-21;
  edits go here, never to the RFC. A decision changes the design, with a
  dated one-line reason.
- `.agents/roadmap.md`, once written, owns the order of work: stages,
  exit criteria, CI tiers, issue links. Until then design §9 is the
  outline.

## Commands

```sh
uv sync --all-extras          # install, including the dev group and duckdb
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format .          # format (Python files only)
uv build                      # sdist and wheel into dist/
```

## CI

`.github/workflows/ci.yml` has two profiles: `quick` on pull requests
(lint, pytest on Ubuntu / 3.13) and `full` on pushes to `main`, manual
runs, and pull requests labelled `full-ci`. Windows is in `full` because
the persisted MSAL cache differs by OS (design §7). A release workflow
with PyPI trusted publishing comes with 0.1.0, as in `py-dazdiff`.

## Rules

- Source lives in `src/dazure/`; public names are re-exported from
  `__init__.py`. `dazure.duckdb` imports `duckdb` lazily: the base
  install must not need it, nor PySpark ever.
- The SDK first (design §3): anything `azure-identity` or `msal` does is
  called, not reimplemented, and the docstring says what it wraps.
- Secrets never print (design §6): refresh tokens, client secrets,
  account keys and bearer tokens are redacted in `repr`, `str`, logs and
  errors, and tests assert it with a sentinel value.
- Spark keys follow `azr::azure_spark_storage_conf()` key for key, except
  where design §4.4 records a divergence.
- Every user-visible change gets a line under the top section of
  `CHANGELOG.md`.

## Definition of done

Tests and `ruff check` / `ruff format --check` pass locally, the pull
request's checks are green at the stage's tier, and the roadmap and the
design are updated in the same pull request.

Merge pull requests with a merge commit (`gh pr merge --merge`), and only
when told to or when running a roadmap loop the user approved.
