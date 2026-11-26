"""`spark_storage_conf()` against `azr::azure_spark_storage_conf()` (design §4.4, §8.1).

The oracle is `tests/fixtures/azr_spark_conf.json`, written by
`tools/azr_spark_fixture.R` from an `azr` checkout with every argument
explicit. The defaults where dazapiz deliberately differs from azr are tested
against the §4.4 list.
"""

import json
from pathlib import Path

import pytest

from dazapiz import (
    AZURE_CLI_CLIENT_ID,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SparkStorageConf,
    spark_storage_conf,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "azr_spark_conf.json").read_text(encoding="utf-8")
)
CASES = FIXTURE["cases"]

ENV = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_REFRESH_TOKEN",
    "AZURE_FEDERATED_TOKEN_FILE",
    "AZURE_AUTHORITY_HOST",
)
P = "spark.hadoop.fs.azure.account."
PROVIDER = "org.apache.hadoop.fs.azurebfs.oauth2."
TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_fixture_records_its_source():
    assert len(FIXTURE["azr_commit"]) == 40
    assert FIXTURE["azr_dirty"] is False
    assert FIXTURE["azr_version"]
    # The full matrix (5 x 3 x 3 x 2) plus two variants per auth type.
    assert len(CASES) == 5 * 3 * 3 * 2 + 5 * 2
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", [c for c in CASES if "conf" in c], ids=lambda c: c["id"])
def test_matches_azr(case, monkeypatch):
    # The environment must play no part when every argument is explicit.
    for name in ENV:
        monkeypatch.setenv(name, "from-the-environment")
    conf = spark_storage_conf(**case["args"])
    assert isinstance(conf, SparkStorageConf)
    assert dict(conf) == case["conf"]
    assert list(conf) == list(case["conf"])  # and in azr's order


@pytest.mark.parametrize("case", [c for c in CASES if "error" in c], ids=lambda c: c["id"])
def test_refuses_what_azr_refuses(case):
    assert "storage_account" in case["error"]
    with pytest.raises(ValueError, match="storage_account"):
        spark_storage_conf(**case["args"])


# Defaults (§4.4): where dazapiz differs from azr, and where it follows it.


def test_refresh_token_info_supplies_its_own_ids(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", "env-client")
    monkeypatch.setenv("AZURE_TENANT_ID", "env-tenant")
    info = RefreshTokenInfo("rt", CLIENT, TENANT, "a@contoso.com")
    conf = spark_storage_conf(refresh_token=info)
    assert conf[P + "oauth2.client.id"] == CLIENT
    assert conf[P + "oauth2.refresh.token"] == "rt"
    assert conf[P + "oauth2.refresh.token.endpoint"] == (
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    )


def test_explicit_ids_override_the_refresh_token_info():
    info = RefreshTokenInfo("rt", CLIENT, TENANT)
    conf = spark_storage_conf(refresh_token=info, client_id="c2", tenant_id="t2")
    assert conf[P + "oauth2.client.id"] == "c2"
    assert conf[P + "oauth2.refresh.token.endpoint"].endswith("/t2/oauth2/v2.0/token")


def test_plain_refresh_token_takes_the_azr_defaults(monkeypatch):
    conf = spark_storage_conf(refresh_token="rt")
    assert conf[P + "oauth2.client.id"] == AZURE_CLI_CLIENT_ID
    assert conf[P + "oauth2.refresh.token.endpoint"].endswith("/common/oauth2/v2.0/token")
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_REFRESH_TOKEN", "env-rt")
    conf = spark_storage_conf()
    assert conf[P + "oauth2.client.id"] == CLIENT
    assert conf[P + "oauth2.refresh.token"] == "env-rt"
    assert conf[P + "oauth2.refresh.token.endpoint"].endswith(f"/{TENANT}/oauth2/v2.0/token")


def test_client_secret_takes_the_environment(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    conf = spark_storage_conf("client_secret")
    assert conf == {
        P + "auth.type": "OAuth",
        P + "oauth.provider.type": PROVIDER + "ClientCredsTokenProvider",
        P + "oauth2.client.id": CLIENT,
        P + "oauth2.client.secret": "s",
        P + "oauth2.client.endpoint": (
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
        ),
    }


def test_managed_identity_without_a_client_id_is_system_assigned(monkeypatch):
    conf = spark_storage_conf("managed_identity")
    assert conf == {
        P + "auth.type": "OAuth",
        P + "oauth.provider.type": PROVIDER + "MsiTokenProvider",
        P + "oauth2.msi.tenant": "common",
        P + "oauth2.msi.authority": "https://login.microsoftonline.com/",
    }
    monkeypatch.setenv("AZURE_CLIENT_ID", "")  # empty counts as unset (D25)
    assert P + "oauth2.client.id" not in spark_storage_conf("managed_identity")


def test_managed_identity_takes_a_user_assigned_client_id(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    conf = spark_storage_conf("managed_identity")
    assert conf[P + "oauth2.client.id"] == CLIENT
    assert conf[P + "oauth2.msi.tenant"] == TENANT


def test_workload_identity_takes_the_environment(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/var/token")
    monkeypatch.setenv("AZURE_AUTHORITY_HOST", "https://login.microsoftonline.us")
    conf = spark_storage_conf("workload_identity", storage_account="acct")
    s = ".acct.dfs.core.usgovcloudapi.net"
    assert conf == {
        P + "auth.type" + s: "OAuth",
        P + "oauth.provider.type" + s: PROVIDER + "WorkloadIdentityTokenProvider",
        P + "oauth2.client.id" + s: CLIENT,
        P + "oauth2.msi.tenant" + s: TENANT,
        P + "oauth2.token.file" + s: "/var/token",
        P + "oauth2.msi.authority" + s: "https://login.microsoftonline.us/",
    }


# Refusals.


@pytest.mark.parametrize("auth_type", ["client_secret", "workload_identity"])
@pytest.mark.parametrize("missing", ["AZURE_CLIENT_ID", "AZURE_TENANT_ID"])
def test_missing_ids_are_refused(auth_type, missing, monkeypatch):
    for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/var/token")
    spark_storage_conf(auth_type)  # complete: no error
    monkeypatch.setenv(missing, "")  # empty counts as unset (D25)
    with pytest.raises(ValueError, match=missing):
        spark_storage_conf(auth_type)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing):
        spark_storage_conf(auth_type)
    # Never the CLI client ID or "common", as azr would.
    arg = "client_id" if missing == "AZURE_CLIENT_ID" else "tenant_id"
    conf = spark_storage_conf(auth_type, **{arg: "given"})
    if arg == "client_id":
        assert conf[P + "oauth2.client.id"] == "given"
    elif auth_type == "client_secret":
        assert (
            conf[P + "oauth2.client.endpoint"]
            == "https://login.microsoftonline.com/given/oauth2/v2.0/token"
        )
    else:
        assert conf[P + "oauth2.msi.tenant"] == "given"


def test_shared_key_needs_an_account_and_a_key():
    with pytest.raises(ValueError, match="storage_account"):
        spark_storage_conf("shared_key", account_key="k")
    with pytest.raises(ValueError, match="account_key"):
        spark_storage_conf("shared_key", storage_account="acct")


def test_missing_secrets_are_refused():
    with pytest.raises(RefreshTokenNotFoundError):
        spark_storage_conf("refresh_token")
    with pytest.raises(ValueError, match="AZURE_CLIENT_SECRET"):
        spark_storage_conf("client_secret", client_id=CLIENT, tenant_id=TENANT)
    with pytest.raises(ValueError, match="AZURE_FEDERATED_TOKEN_FILE"):
        spark_storage_conf("workload_identity", client_id=CLIENT, tenant_id=TENANT)


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        (
            {"auth_type": "sas"},
            ValueError,
            "auth_type must be one of refresh_token, client_secret, workload_identity, "
            "managed_identity, shared_key, not 'sas'",
        ),
        ({"prefix": ""}, ValueError, "prefix must not be empty"),
        ({"storage_account": ""}, ValueError, "storage_account must not be empty"),
        ({"authority_host": ""}, ValueError, "authority_host must not be empty"),
        ({"authority_host": "///"}, ValueError, "authority_host '///' has no host"),
        ({"tenant_id": "a/b"}, ValueError, "tenant_id 'a/b' is not a valid tenant ID"),
        ({"tenant_id": ""}, ValueError, "tenant_id must not be empty"),
        ({"client_id": ""}, ValueError, "client_id must not be empty"),
        (
            {"auth_type": "managed_identity", "tenant_id": "a b"},
            ValueError,
            "tenant_id 'a b' is not a valid tenant ID",
        ),
        ({"storage_account": 1}, TypeError, "storage_account must be a str or None, not int"),
    ],
    ids=lambda v: repr(v) if isinstance(v, dict) else "",
)
def test_invalid_arguments_are_refused(kwargs, error, message):
    kwargs = {"refresh_token": "rt", **kwargs}
    with pytest.raises(error) as err:
        spark_storage_conf(**kwargs)
    assert type(err.value) is error
    assert str(err.value) == message


def test_secrets_of_other_auth_types_are_ignored():
    # As in azr: arguments another auth type uses are accepted and left out.
    conf = spark_storage_conf(
        refresh_token="rt", client_secret="s", account_key="k", token_file="/f"
    )
    assert set(conf.values()) & {"s", "k", "/f"} == set()


def test_union_with_a_non_dict_follows_dict():
    # As dict's own `|`: a non-dict operand gets its turn, and with none, TypeError.
    conf = SparkStorageConf({"k": "v"})

    class Other:
        def __ror__(self, left):
            return "other's result"

    assert conf | Other() == "other's result"
    with pytest.raises(TypeError, match="unsupported operand"):
        conf | 1
    with pytest.raises(TypeError, match="unsupported operand"):
        1 | conf
    assert type({"a": "b"} | conf) is SparkStorageConf
