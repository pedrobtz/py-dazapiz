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
- `.agents/roadmap.md` owns the order of work: stages, exit criteria,
  CI tiers, issue links. Each stage is a sub-issue of `v0.1.0` (#2),
  closed by one pull request titled like the stage, with `Closes #<n>`.

## Commands

```sh
uv sync --all-extras          # install, including the dev group and duckdb
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format .          # format (Python files only)
uv run pyright                # strict type check of src/, examples/, tests/typing/
uv run python examples/petstore.py   # the Petstore example, against the public store
DAZURE_LIVE_HTTP=1 uv run pytest tests/manual/test_live_petstore.py  # its live test
uv build                      # sdist and wheel into dist/
uv run --python 3.13 --with great-docs==0.17.0 great-docs lint     # docstring checks
uv run --python 3.13 --with great-docs==0.17.0 great-docs build    # site into great-docs/_site
uv run --python 3.13 --with great-docs==0.17.0 great-docs preview  # serve it locally
```

The site build needs Quarto 1.11.9 on `PATH`.

## CI

`.github/workflows/ci.yml` has two profiles: `quick` on pull requests
(lint: ruff and pyright; pytest on Ubuntu / 3.13) and `full` on pushes
to `main`, manual runs, and pull requests labelled `full-ci`. Windows is in `full` for the
platform branches (design §7); `full` also has a coverage job (Ubuntu /
3.13) whose `--cov-fail-under` floor is the level reached, less a point.
A release workflow with PyPI trusted publishing comes with 0.1.0, as in
`py-dazdiff`. `.github/workflows/docs.yml` runs `great-docs lint` and
builds the site on every pull request and push to `main`, and deploys it to
GitHub Pages from `main` (great-docs and Quarto pinned).

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
- Tests in CI touch no Azure: only plain data or a simple mock
  (`httpx.MockTransport`, a local httpbin on loopback, a fake `az` on
  `PATH`, one `msal` method patched). Anything needing a fake Entra authority or a real OS secret
  store goes on the manual checklist in `tests/manual/README.md`
  (design §8.2), run by hand with full Azure access.
- `pyright` is strict (design D55): fix what it finds; an ignore names its
  rule and its reason, and only azure-identity's private API has one.
  pydantic is a dev dependency (tests and `examples/`), never imported
  by `src/`.
- `examples/` is repository-only: not in the sdist or the wheel.
- The documentation site is `great-docs.yml` (API reference groups,
  following design §5), `user_guide/*.qmd` (guide pages) and the NumPy
  docstrings. A new public name gets a NumPy docstring (summary,
  `Parameters`, `Returns`, `Raises`, `Notes` saying what it wraps, a short
  `Examples`) and an entry in a `reference` group; `dazure.duckdb` names
  are listed as `duckdb.<name>`. Guide code needs Azure, so it never runs:
  plain code blocks only. Code from `examples/` is included by line range
  under a `<!-- snippet: <first line> -->` marker, which
  `tests/test_docs_snippets.py` checks; move the range when the file
  changes.
- Every user-visible change gets a line under the top section of
  `CHANGELOG.md`.

## Definition of done

Tests, `ruff check` / `ruff format --check` and `pyright` pass locally,
the pull request's checks are green at the stage's tier, and the roadmap and the
design are updated in the same pull request.

Merge pull requests with a merge commit (`gh pr merge --merge`), and only
when told to or when running a roadmap loop the user approved.
