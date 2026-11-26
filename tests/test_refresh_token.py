"""RefreshTokenInfo, SupportsRefreshToken and the design §4.3.4 defaults."""

import dataclasses

import pytest

from dazapiz import (
    AZURE_CLI_CLIENT_ID,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SupportsRefreshToken,
)
from dazapiz._refresh_token import as_refresh_token_info

ENV = ("AZURE_REFRESH_TOKEN", "AZURE_CLIENT_ID", "AZURE_TENANT_ID")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_cli_client_id_is_azr_s():
    # azr R/constants.R
    assert AZURE_CLI_CLIENT_ID == "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def test_info_is_frozen_and_its_own_refresh_token():
    info = RefreshTokenInfo("rt", "cid", "tid", "a@x")
    assert info.get_refresh_token() is info
    assert isinstance(info, SupportsRefreshToken)
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.token = "other"


@pytest.mark.parametrize("field", ["token", "client_id", "tenant_id"])
@pytest.mark.parametrize("value", ["", None, 1])
def test_info_refuses_empty_fields(field, value):
    args = {"token": "rt", "client_id": "cid", "tenant_id": "tid", field: value}
    with pytest.raises((TypeError, ValueError), match=field):
        RefreshTokenInfo(**args)


# The §4.3.4 table: what a plain string, or nothing, becomes.
@pytest.mark.parametrize(
    ("env", "given", "expected"),
    [
        ({}, "rt", ("rt", AZURE_CLI_CLIENT_ID, "common")),
        ({"AZURE_CLIENT_ID": "cid"}, "rt", ("rt", "cid", "common")),
        ({"AZURE_TENANT_ID": "tid"}, "rt", ("rt", AZURE_CLI_CLIENT_ID, "tid")),
        ({"AZURE_CLIENT_ID": "cid", "AZURE_TENANT_ID": "tid"}, "rt", ("rt", "cid", "tid")),
        ({"AZURE_REFRESH_TOKEN": "env-rt"}, None, ("env-rt", AZURE_CLI_CLIENT_ID, "common")),
        (
            {"AZURE_REFRESH_TOKEN": "env-rt", "AZURE_CLIENT_ID": "cid", "AZURE_TENANT_ID": "tid"},
            None,
            ("env-rt", "cid", "tid"),
        ),
        # A given string wins over $AZURE_REFRESH_TOKEN.
        ({"AZURE_REFRESH_TOKEN": "env-rt"}, "rt", ("rt", AZURE_CLI_CLIENT_ID, "common")),
        # Empty variables count as unset (azr would pass the empty string on; design §4.3.4).
        (
            {"AZURE_CLIENT_ID": "", "AZURE_TENANT_ID": ""},
            "rt",
            ("rt", AZURE_CLI_CLIENT_ID, "common"),
        ),
    ],
)
def test_string_and_environment_defaults(monkeypatch, env, given, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    info = as_refresh_token_info(given)
    assert (info.token, info.client_id, info.tenant_id, info.username) == (*expected, None)


@pytest.mark.parametrize("env_value", [None, ""])
def test_nothing_given_and_no_variable_is_not_found(monkeypatch, env_value):
    if env_value is not None:
        monkeypatch.setenv("AZURE_REFRESH_TOKEN", env_value)
    with pytest.raises(RefreshTokenNotFoundError, match="AZURE_REFRESH_TOKEN"):
        as_refresh_token_info(None)


def test_supports_refresh_token_keeps_its_own_ids(monkeypatch):
    monkeypatch.setenv("AZURE_REFRESH_TOKEN", "env-rt")
    monkeypatch.setenv("AZURE_CLIENT_ID", "env-cid")
    monkeypatch.setenv("AZURE_TENANT_ID", "env-tid")
    own = RefreshTokenInfo("rt", "cid", "tid", "a@x")

    class Source:
        def get_refresh_token(self):
            return own

    assert as_refresh_token_info(Source()) is own
    assert as_refresh_token_info(own) is own


def test_refusals():
    with pytest.raises(ValueError, match="empty"):
        as_refresh_token_info("")
    with pytest.raises(TypeError, match="SupportsRefreshToken"):
        as_refresh_token_info(42)

    class Liar:
        def get_refresh_token(self):
            return "rt"

    with pytest.raises(TypeError, match="RefreshTokenInfo"):
        as_refresh_token_info(Liar())


def test_info_refuses_a_non_string_username():
    with pytest.raises(TypeError, match="username"):
        RefreshTokenInfo("rt", "cid", "tid", 42)
