# dazapiz

[![CI](https://github.com/pedrobtz/py-dazapiz/actions/workflows/ci.yml/badge.svg)](https://github.com/pedrobtz/py-dazapiz/actions/workflows/ci.yml)
[![Docs](https://github.com/pedrobtz/py-dazapiz/actions/workflows/docs.yml/badge.svg)](https://pedrobtz.github.io/py-dazapiz/)
[![PyPI](https://img.shields.io/pypi/v/dazapiz)](https://pypi.org/project/dazapiz/)

The Azure helpers `azure-identity` lacks: your `az login` in Python,
carried into Spark, DuckDB and any Azure REST API, with one small package
on top of the official SDK. Documentation:
<https://pedrobtz.github.io/py-dazapiz/>.

- **Spark from your `az login`.** Neither PySpark nor the Azure SDK turns
  an `az login` into Spark's ABFS settings; `spark_storage_conf()` finds
  the refresh token the Azure CLI keeps and writes the keys.
- **A REST client for one API.** `ApiClient` is a typed `httpx` client:
  bearer token, retries, parsing, and errors that never show a secret.
- **DuckDB secrets** from any credential, scoped per storage account.
- **Sign-in that works in a browser-hosted IDE**: device code, browser,
  and a pasted-code flow for code-server and cloud notebooks.

Where `azure-identity` or `msal` already does a job, `dazapiz` calls it.

## Installation

From [PyPI](https://pypi.org/project/dazapiz/):

```sh
pip install dazapiz
```

It needs Python 3.10 or later. The `duckdb` extra adds the DuckDB secrets:

```sh
pip install "dazapiz[duckdb]"
```

The development version installs from GitHub:
`pip install git+https://github.com/pedrobtz/py-dazapiz`.

## A first run

```python
from dazapiz import az_login, spark_storage_conf, refresh_token_from_az_cli

az_login()                                 # device code, once per machine
conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
spark = SparkSession.builder.config(map=conf).getOrCreate()
```

- [Get started](https://pedrobtz.github.io/py-dazapiz/user-guide/get-started.html):
  install, `az login`, Spark, and the other ways to authenticate.
- [REST client](https://pedrobtz.github.io/py-dazapiz/user-guide/rest-client.html):
  a typed client for one Azure-protected API, with a Petstore example.
- [DuckDB](https://pedrobtz.github.io/py-dazapiz/user-guide/duckdb.html):
  Azure secrets from any credential, scoped per account.
- [Browser-hosted sign-in](https://pedrobtz.github.io/py-dazapiz/user-guide/browser-sign-in.html):
  device code, browser, and the pasted-code flow for code-server.
- [Testing your API client](https://pedrobtz.github.io/py-dazapiz/user-guide/testing.html):
  an `ApiClient` subclass tested in CI without Azure.
- The [reference](https://pedrobtz.github.io/py-dazapiz/reference/) lists
  every public name.

## Status

0.1.0 is the first release; the interface may still change before 1.0.
Changes are listed in
[`CHANGELOG.md`](https://github.com/pedrobtz/py-dazapiz/blob/main/CHANGELOG.md).
The design is in
[`.agents/design.md`](https://github.com/pedrobtz/py-dazapiz/blob/main/.agents/design.md)
and the order of work in
[`.agents/roadmap.md`](https://github.com/pedrobtz/py-dazapiz/blob/main/.agents/roadmap.md).

## License

MIT
