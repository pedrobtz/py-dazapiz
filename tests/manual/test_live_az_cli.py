"""Checklist items 1 and 5: the `az login` refresh token, and the read-only `az` helpers.

Needs `az` installed and logged in (`az login`). Skipped unless `DAZURE_LIVE=1`.
"""

from __future__ import annotations

import time

from live_helpers import ARM_SCOPE

import dazure
from dazure import RefreshTokenCredential, refresh_token_from_az_cli


def _redeem(info: dazure.RefreshTokenInfo, claims) -> dict:
    credential = RefreshTokenCredential(info)
    access = credential.get_token(ARM_SCOPE)
    assert access.expires_on > time.time() + 60
    assert info.token not in repr(info)
    assert info.token not in repr(credential)
    assert access.token not in repr(credential)
    # Entra may rotate the refresh token; the credential keeps the new one.
    assert credential.get_refresh_token().client_id == info.client_id
    return claims(access.token)


def test_refresh_token_from_az_cli_is_redeemed(posix_only, claims):
    info = refresh_token_from_az_cli()
    assert info.client_id == dazure.AZURE_CLI_CLIENT_ID
    account = dazure.az_account_show()
    assert info.tenant_id == account["tenantId"]
    assert (info.username or "").lower() == account["user"]["name"].lower()

    token_claims = _redeem(info, claims)
    assert token_claims["tid"] == account["tenantId"]
    assert token_claims["aud"].rstrip("/") == "https://management.azure.com"


def test_refresh_token_from_az_cli_guest_tenant(posix_only, env, claims):
    guest = env("DAZURE_TEST_GUEST_TENANT_ID")
    info = refresh_token_from_az_cli(tenant_id=guest)
    assert info.tenant_id == guest
    assert _redeem(info, claims)["tid"] == guest


def test_az_is_login_and_account_show():
    assert dazure.az_is_login() is True
    account = dazure.az_account_show()
    assert account["tenantId"]
    assert account["user"]["name"]
    assert "accessToken" not in account
