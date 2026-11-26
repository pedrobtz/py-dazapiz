"""Checklist item 4: `ApiClient.fetch()` against ARM, with `app_credential()` in dev and prod.

`dev` needs `az` logged in (`AzureCliCredential` is first in the chain, so
no device code is asked for). `prod` needs the test service principal in
`DAZAPIZ_TEST_TENANT_ID`, `DAZAPIZ_TEST_CLIENT_ID` and
`DAZAPIZ_TEST_CLIENT_SECRET`. Skipped unless `DAZAPIZ_LIVE=1`.
"""

from __future__ import annotations

import logging

import pytest
from azure.identity import ChainedTokenCredential, ClientSecretCredential
from live_helpers import ARM, ARM_SCOPE

import dazapiz
from dazapiz import ApiClient, app_credential

SUBSCRIPTIONS = {"api-version": "2022-12-01"}


class Arm(ApiClient):
    host_url = ARM
    scope = ARM_SCOPE
    client_id_env = "DAZAPIZ_TEST_CLIENT_ID"
    client_secret_env = "DAZAPIZ_TEST_CLIENT_SECRET"
    tenant_id_env = "DAZAPIZ_TEST_TENANT_ID"


def _fetch_logged(credential, caplog) -> dict:
    caplog.set_level(logging.DEBUG, logger="dazapiz")
    with Arm(credential=credential, verbose=True) as client:
        result = client.fetch("/subscriptions", query=SUBSCRIPTIONS)
    bearer = credential.get_token(ARM_SCOPE).token
    assert bearer not in caplog.text
    assert any(">>> GET" in r.getMessage() for r in caplog.records)
    assert isinstance(result, dict)
    assert isinstance(result["value"], list)
    return result


def test_fetch_dev(caplog):
    credential = app_credential(
        "DAZAPIZ_TEST_CLIENT_ID",
        "DAZAPIZ_TEST_CLIENT_SECRET",
        tenant_id_env="DAZAPIZ_TEST_TENANT_ID",
        mode="dev",
    )
    assert isinstance(credential, ChainedTokenCredential)
    result = _fetch_logged(credential, caplog)
    ids = {s["subscriptionId"] for s in result["value"]}
    assert dazapiz.az_account_show()["id"] in ids


def test_fetch_prod(service_principal, caplog):
    credential = app_credential(
        "DAZAPIZ_TEST_CLIENT_ID",
        "DAZAPIZ_TEST_CLIENT_SECRET",
        tenant_id_env="DAZAPIZ_TEST_TENANT_ID",
        mode="prod",
    )
    assert isinstance(credential, ClientSecretCredential)
    _fetch_logged(credential, caplog)
    assert service_principal[2] not in caplog.text


def test_fetch_error_is_api_error(service_principal):
    with Arm() as client, pytest.raises(dazapiz.ApiError) as raised:
        client.fetch("/subscriptions/{id}", query=SUBSCRIPTIONS, id="not-a-subscription")
    assert raised.value.response.status_code in (400, 403, 404)
