"""Checklist item 6: a local PySpark read from ADLS with `spark_storage_conf()`.

Needs PySpark, Java, and the `hadoop-azure` package matching the Hadoop
that PySpark bundles: `DAZURE_SPARK_PACKAGES` (default
`org.apache.hadoop:hadoop-azure:3.4.1` for PySpark 4,
`org.apache.hadoop:hadoop-azure:3.3.4` for PySpark 3.5), fetched by Spark
from Maven Central on first use. Each test starts and stops its own
session, so the two auth types never share a cached ABFS file system.
Skipped unless `DAZURE_LIVE=1`, and when PySpark is not installed.
"""

from __future__ import annotations

import os
import re

import pytest

from dazure import refresh_token_from_az_cli, spark_storage_conf

_HADOOP_AZURE = {"3": "3.3.4", "4": "3.4.1"}


def _packages(pyspark) -> str:
    explicit = os.environ.get("DAZURE_SPARK_PACKAGES")
    if explicit:
        return explicit
    version = _HADOOP_AZURE.get(pyspark.__version__.split(".")[0])
    if version is None:
        pytest.skip(f"set DAZURE_SPARK_PACKAGES for PySpark {pyspark.__version__}")
    return f"org.apache.hadoop:hadoop-azure:{version}"


@pytest.fixture
def spark_session():
    """`spark_session(conf)`: a local session with `conf` (spark.hadoop keys) applied."""
    pyspark = pytest.importorskip("pyspark", reason="PySpark is not installed")
    from pyspark.sql import SparkSession

    sessions = []

    def start(conf):
        builder = (
            SparkSession.builder.master("local[1]")
            .appName("dazure-live")
            .config("spark.jars.packages", _packages(pyspark))
            .config("spark.ui.enabled", "false")
        )
        for key, value in conf.items():
            builder = builder.config(key, value)
        session = builder.getOrCreate()
        sessions.append(session)
        return session

    yield start
    for session in sessions:
        session.stop()


def _read(spark, storage) -> int:
    account, container, path, rows = storage
    url = f"abfss://{container}@{account}.dfs.core.windows.net/{path}"
    reader = spark.read
    if path.endswith(".parquet"):
        frame = reader.parquet(url)
    elif path.endswith(".csv"):
        frame = reader.option("header", "true").csv(url)
    elif path.endswith(".json"):
        frame = reader.json(url)
    else:
        frame = reader.text(url)
    count = frame.count()
    if rows is None:
        assert count >= 1
    else:
        assert count == rows
    return count


def _hadoop_version(spark) -> str:
    return spark.sparkContext._jvm.org.apache.hadoop.util.VersionInfo.getVersion()


def _has_class(spark, dotted: str) -> bool:
    node = spark.sparkContext._jvm
    for part in dotted.split("."):
        node = getattr(node, part)
    return type(node).__name__ == "JavaClass"


def test_read_with_az_cli_refresh_token(spark_session, posix_only, storage):
    conf = spark_storage_conf(refresh_token=refresh_token_from_az_cli(), storage_account=storage[0])
    _read(spark_session(conf), storage)


def test_read_with_service_principal(spark_session, storage, service_principal):
    tenant_id, client_id, client_secret = service_principal
    conf = spark_storage_conf(
        "client_secret",
        storage_account=storage[0],
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    _read(spark_session(conf), storage)


def test_workload_identity_provider_needs_hadoop_3_4_1(spark_session, record_property):
    """Design §12's note: `WorkloadIdentityTokenProvider` is in hadoop-azure 3.4.1+."""
    spark = spark_session({})
    version = _hadoop_version(spark)
    record_property("hadoop_version", version)
    provider = "org.apache.hadoop.fs.azurebfs.oauth2"
    assert _has_class(spark, f"{provider}.ClientCredsTokenProvider"), "hadoop-azure not loaded"
    expected = tuple(int(p) for p in re.findall(r"\d+", version)[:3]) >= (3, 4, 1)
    assert _has_class(spark, f"{provider}.WorkloadIdentityTokenProvider") is expected, version
