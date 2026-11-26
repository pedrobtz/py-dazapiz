# dazapiz

The Azure helpers `azure-identity` lacks: your `az login` in Python,
carried into Spark, DuckDB and any Azure REST API, with one small package
on top of the official SDK.

```sh
pip install dazapiz            # or "dazapiz[duckdb]" for the DuckDB secrets
```

```python
from dazapiz import az_login, spark_storage_conf, refresh_token_from_az_cli

az_login()                                 # device code, once per machine
conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
spark = SparkSession.builder.config(map=conf).getOrCreate()
```

Neither PySpark nor the Azure SDK turns an `az login` into Spark's ABFS
settings; `dazapiz` finds the refresh token the Azure CLI keeps and writes
the keys. Where `azure-identity` or `msal` already does a job, `dazapiz`
calls it.

- [Get started](https://pedrobtz.github.io/py-dazapiz/user-guide/get-started.html):
  install, `az login`, Spark, and the other ways to authenticate.
- [REST client](https://pedrobtz.github.io/py-dazapiz/user-guide/rest-client.html):
  a typed `httpx` client for one Azure-protected API, with a Petstore example.
- [DuckDB](https://pedrobtz.github.io/py-dazapiz/user-guide/duckdb.html):
  Azure secrets from any credential, scoped per account.
- [Browser-hosted sign-in](https://pedrobtz.github.io/py-dazapiz/user-guide/browser-sign-in.html):
  device code, browser, and the pasted-code flow for code-server.
- [Reference](https://pedrobtz.github.io/py-dazapiz/reference/)

Pre-release: until 0.1.0 is on PyPI, install from GitHub with
`pip install "dazapiz @ git+https://github.com/pedrobtz/py-dazapiz"`. The
design is in [`.agents/design.md`](https://github.com/pedrobtz/py-dazapiz/blob/main/.agents/design.md).

## License

MIT
