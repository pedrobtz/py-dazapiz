# dazure

The Azure helpers `azure-identity` lacks: your `az login` in Python,
carried into Spark, DuckDB and any Azure REST API, with one small package
on top of the official SDK.

```python
from dazure import az_login, spark_storage_conf, refresh_token_from_az_cli

az_login()                                 # device code, once per machine
conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli())
spark = SparkSession.builder.config(map=conf).getOrCreate()
```

Not built yet. The design is in [`.agents/design.md`](.agents/design.md).

## License

MIT
