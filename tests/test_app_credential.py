"""app_credential(): every mode and partly set case, by type and constructor arguments.

Each azure-identity class is replaced in `dazure._app_credential` by a
subclass that records its constructor arguments and then builds the real
thing, so the result has the real type and no token is ever fetched.
"""

from __future__ import annotations

import logging

import azure.identity
import pytest

import dazure
import dazure._app_credential
import dazure._session
from dazure import app_credential

INFO = "\N{INFORMATION SOURCE}"
ID, SECRET, TENANT = "APP_ID", "APP_SECRET", "APP_TENANT"
CLASSES = [
    "AzureCliCredential",
    "ChainedTokenCredential",
    "ClientSecretCredential",
    "ManagedIdentityCredential",
    "WorkloadIdentityCredential",
    "DeviceCodeCredential",
]
ENV = [
    ID,
    SECRET,
    TENANT,
    "AZURE_TOKEN_CREDENTIALS",
    "AZURE_FEDERATED_TOKEN_FILE",
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "IDENTITY_ENDPOINT",
    "MSI_ENDPOINT",
]


@pytest.fixture
def built(monkeypatch) -> list[tuple[str, tuple, dict]]:
    """Clear the environment, fake an interactive session and record every construction."""
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(dazure._session, "is_interactive", lambda: True)
    calls: list[tuple[str, tuple, dict]] = []
    for name in CLASSES:
        real = getattr(dazure._app_credential, name)

        def init(self, *args, _real=real, _name=name, **kwargs):
            calls.append((_name, args, kwargs))
            _real.__init__(self, *args, **kwargs)

        monkeypatch.setattr(dazure._app_credential, name, type(name, (real,), {"__init__": init}))
    return calls


def set_sp(monkeypatch, client_id="cid", secret="s3cret", tenant="tid"):
    for name, value in ((ID, client_id), (SECRET, secret), (TENANT, tenant)):
        if value is not None:
            monkeypatch.setenv(name, value)


def credential(mode=None):
    return app_credential(ID, SECRET, tenant_id_env=TENANT, mode=mode)


def names(calls):
    return [name for name, _, _ in calls]


SP_CALL = (
    "ClientSecretCredential",
    (),
    {"tenant_id": "tid", "client_id": "cid", "client_secret": "s3cret"},
)


# prod ----------------------------------------------------------------------


def test_prod_service_principal_first(built, monkeypatch):
    set_sp(monkeypatch)
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/tmp/token")
    cred = credential("prod")
    assert isinstance(cred, azure.identity.ClientSecretCredential)
    assert built == [SP_CALL]


def test_prod_workload_identity_then_managed_identity(built, monkeypatch):
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/tmp/token")
    monkeypatch.setenv("AZURE_CLIENT_ID", "wid")
    monkeypatch.setenv("AZURE_TENANT_ID", "wtid")
    cred = credential("prod")
    assert isinstance(cred, azure.identity.WorkloadIdentityCredential)
    assert built == [("WorkloadIdentityCredential", (), {})]

    monkeypatch.delenv("AZURE_FEDERATED_TOKEN_FILE")
    built.clear()
    cred = credential("prod")
    assert isinstance(cred, azure.identity.ManagedIdentityCredential)
    assert built == [("ManagedIdentityCredential", (), {})]


@pytest.mark.parametrize("mode", ["prod", "client_secret", None])
@pytest.mark.parametrize(
    ("given", "missing"),
    [
        ({"secret": None}, f"{ID} is set but {SECRET} is not"),
        ({"client_id": None}, f"{SECRET} is set but {ID} is not"),
        ({"tenant": None}, f"{ID} and {SECRET} are set but {TENANT} is not"),
        ({"secret": ""}, f"{ID} is set but {SECRET} is not"),  # empty counts as unset
    ],
)
def test_partly_set_service_principal_is_an_error(built, monkeypatch, mode, given, missing):
    set_sp(monkeypatch, **given)
    with pytest.raises(ValueError) as err:
        credential(mode)
    assert missing in str(err.value)
    assert "s3cret" not in str(err.value)
    assert built == []


def test_client_secret_mode_needs_the_service_principal(built):
    with pytest.raises(ValueError, match=f"{ID} and {SECRET} are not set"):
        credential("client_secret")


def test_tenant_defaults_to_azure_tenant_id(built, monkeypatch):
    monkeypatch.setenv(ID, "cid")
    monkeypatch.setenv(SECRET, "s3cret")
    monkeypatch.setenv("AZURE_TENANT_ID", "tid")
    app_credential(ID, SECRET, mode="prod")
    assert built == [SP_CALL]


# dev ------------------------------------------------------------------------


def test_dev_chain_with_device_code_when_interactive(built, monkeypatch):
    set_sp(monkeypatch)  # dev ignores the service principal
    cred = credential("dev")
    assert isinstance(cred, azure.identity.ChainedTokenCredential)
    cli, device = cred.credentials
    assert isinstance(cli, azure.identity.AzureCliCredential)
    assert isinstance(device, dazure.DeviceCodeCredential)
    assert names(built) == ["AzureCliCredential", "DeviceCodeCredential", "ChainedTokenCredential"]
    assert all(
        args == () and kwargs == {}
        for name, args, kwargs in built
        if name != "ChainedTokenCredential"
    )


def test_dev_chain_without_device_code_when_not_interactive(built, monkeypatch):
    monkeypatch.setattr(dazure._session, "is_interactive", lambda: False)
    cred = credential("dev")
    (cli,) = cred.credentials
    assert isinstance(cli, azure.identity.AzureCliCredential)
    assert "DeviceCodeCredential" not in names(built)


# single names ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("workload_identity", "WorkloadIdentityCredential"),
        ("WorkloadIdentityCredential", "WorkloadIdentityCredential"),
        ("managed_identity", "ManagedIdentityCredential"),
        ("MANAGEDIDENTITYCREDENTIAL", "ManagedIdentityCredential"),
        ("azure_cli", "AzureCliCredential"),
        ("AzureCliCredential", "AzureCliCredential"),
        ("Device_Code", "DeviceCodeCredential"),
        ("devicecodecredential", "DeviceCodeCredential"),
    ],
)
def test_single_names_case_insensitive(built, monkeypatch, mode, expected):
    set_sp(monkeypatch)  # a single name other than client_secret ignores it
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/tmp/token")
    monkeypatch.setenv("AZURE_CLIENT_ID", "wid")
    monkeypatch.setenv("AZURE_TENANT_ID", "wtid")
    cred = credential(mode)
    assert type(cred).__name__ == expected
    assert built == [(expected, (), {})]


@pytest.mark.parametrize(
    "mode", ["client_secret", "Client_Secret", "ClientSecretCredential", "EnvironmentCredential"]
)
def test_single_name_client_secret(built, monkeypatch, mode):
    set_sp(monkeypatch)
    assert isinstance(credential(mode), azure.identity.ClientSecretCredential)
    assert built == [SP_CALL]


@pytest.mark.parametrize("mode", ["Dev", " PROD "])
def test_groups_case_insensitive(built, monkeypatch, mode):
    set_sp(monkeypatch)
    cred = credential(mode)
    expected = "ChainedTokenCredential" if "dev" in mode.lower() else "ClientSecretCredential"
    assert type(cred).__name__ == expected


@pytest.mark.parametrize("mode", ["staging", "AzurePowerShellCredential", "interactive_browser"])
def test_unknown_mode_is_an_error(built, mode):
    with pytest.raises(ValueError, match="Unknown credential mode"):
        credential(mode)


# where the mode comes from, and automatic ---------------------------------------------


def test_mode_from_azure_token_credentials(built, monkeypatch):
    monkeypatch.setenv("AZURE_TOKEN_CREDENTIALS", "managedidentitycredential")
    assert isinstance(credential(), azure.identity.ManagedIdentityCredential)
    built.clear()
    # The argument (or class attribute) wins over the variable.
    assert isinstance(credential("azure_cli"), azure.identity.AzureCliCredential)
    monkeypatch.setenv("AZURE_TOKEN_CREDENTIALS", "nonsense")
    with pytest.raises(ValueError, match="AZURE_TOKEN_CREDENTIALS"):
        credential()
    monkeypatch.setenv("AZURE_TOKEN_CREDENTIALS", "")  # empty is unset: automatic
    assert isinstance(credential(), azure.identity.ChainedTokenCredential)


def test_automatic_service_principal_when_set(built, monkeypatch):
    set_sp(monkeypatch)
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/tmp/token")
    assert isinstance(credential(), azure.identity.ClientSecretCredential)
    assert built == [SP_CALL]


def test_automatic_dev_otherwise(built, monkeypatch):
    # Managed and workload identity are only used when asked for (D20).
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/tmp/token")
    monkeypatch.setenv(TENANT, "tid")
    cred = credential()
    assert isinstance(cred, azure.identity.ChainedTokenCredential)
    assert names(built) == ["AzureCliCredential", "DeviceCodeCredential", "ChainedTokenCredential"]


def test_two_apis_read_their_own_variables(built, monkeypatch):
    set_sp(monkeypatch)
    monkeypatch.setenv("OTHER_ID", "cid2")
    monkeypatch.setenv("OTHER_SECRET", "s2")
    app_credential(ID, SECRET, tenant_id_env=TENANT)
    app_credential("OTHER_ID", "OTHER_SECRET", tenant_id_env=TENANT)
    assert [kw for _, _, kw in built] == [
        SP_CALL[2],
        {"tenant_id": "tid", "client_id": "cid2", "client_secret": "s2"},
    ]


def test_choice_logged_at_info(built, monkeypatch, caplog):
    set_sp(monkeypatch)
    with caplog.at_level(logging.INFO, logger="dazure.http"):
        credential()
        credential("dev")
        monkeypatch.setenv("AZURE_TOKEN_CREDENTIALS", "prod")
        credential()
    assert [(r.name, r.levelno) for r in caplog.records] == [("dazure.http", logging.INFO)] * 3
    assert [r.getMessage() for r in caplog.records] == [
        f"{INFO} Credential: ClientSecretCredential, mode client_secret (automatic).",
        f"{INFO} Credential: ChainedTokenCredential(AzureCliCredential, DeviceCodeCredential), mode dev (from mode).",
        f"{INFO} Credential: ClientSecretCredential, mode prod (from AZURE_TOKEN_CREDENTIALS).",
    ]
