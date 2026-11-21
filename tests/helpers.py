"""Write an Azure CLI config directory the way `az login` leaves it.

The token cache is written by `msal.SerializableTokenCache.add()` from a fake
token response, so its schema (keys, `home_account_id`, `username`) comes
from `msal` itself rather than from hand-written JSON. `client_info` and
`id_token` are built so that `msal` derives `home_account_id` as
`<uid>.<home tenant>` and `username` from `preferred_username`, as it does
for a real Entra response.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import msal

from dazure import AZURE_CLI_CLIENT_ID

ENVIRONMENT = "login.microsoftonline.com"
SCOPE = ["https://management.core.windows.net//.default"]


def _b64url(obj: dict) -> str:
    raw = json.dumps(obj).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uid(username: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, username))


@dataclass(frozen=True)
class Login:
    """One `az login` of `username` (homed in `home_tenant`) into `tenant_id`."""

    username: str
    home_tenant: str
    tenant_id: str
    refresh_token: str
    client_id: str = AZURE_CLI_CLIENT_ID
    environment: str = ENVIRONMENT
    scope: tuple[str, ...] = tuple(SCOPE)
    now: int | None = None  # the time msal records, for ordering refresh tokens

    @property
    def home_account_id(self) -> str:
        return f"{_uid(self.username)}.{self.home_tenant}"

    def id_token_claims(self) -> dict:
        """The ID token's claims, as Entra issues them and msal decodes them."""
        uid = _uid(self.username)
        return {
            "aud": self.client_id,
            "iss": f"https://{self.environment}/{self.tenant_id}/v2.0",
            "tid": self.tenant_id,
            "oid": uid if self.tenant_id == self.home_tenant else _uid(self.username + "#guest"),
            "sub": uid,
            "preferred_username": self.username,
        }

    def token_response(self) -> dict:
        """A token endpoint response as Entra returns it to the Azure CLI."""
        uid = _uid(self.username)
        claims = self.id_token_claims()
        return {
            "token_type": "Bearer",
            "scope": " ".join(self.scope),
            "expires_in": 3600,
            "access_token": f"access-{self.refresh_token}",
            "refresh_token": self.refresh_token,
            "foci": "1",
            "id_token": f"{_b64url({'alg': 'none'})}.{_b64url(claims)}.",
            "client_info": _b64url({"uid": uid, "utid": self.home_tenant}),
        }

    def token_result(self) -> dict:
        """What msal's `acquire_token_*()` returns: the response with its decoded claims."""
        return {**self.token_response(), "id_token_claims": self.id_token_claims()}


def token_cache(logins: list[Login]) -> msal.SerializableTokenCache:
    """An msal cache holding `logins`, added in order through msal."""
    cache = msal.SerializableTokenCache()
    for login in logins:
        cache.add(
            {
                "client_id": login.client_id,
                "scope": list(login.scope),
                "token_endpoint": f"https://{login.environment}/{login.tenant_id}/oauth2/v2.0/token",
                "response": login.token_response(),
                "grant_type": "device_code",
            },
            now=login.now,
        )
    return cache


def write_token_cache(config_dir: Path, logins: list[Login]) -> Path:
    """Write `msal_token_cache.json` holding `logins`, in order, through msal."""
    cache = token_cache(logins)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "msal_token_cache.json"
    path.write_text(cache.serialize(), encoding="utf-8")
    return path


def subscription(username: str, tenant_id: str, *, is_default: bool = False) -> dict:
    """One `azureProfile.json` subscription, as `az login` writes it."""
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{username}/{tenant_id}")),
        "name": f"subscription of {username} in {tenant_id}",
        "state": "Enabled",
        "user": {"name": username, "type": "user"},
        "isDefault": is_default,
        "tenantId": tenant_id,
        "environmentName": "AzureCloud",
        "homeTenantId": tenant_id,
        "managedByTenants": [],
    }


def write_profile(config_dir: Path, subscriptions: list[dict]) -> Path:
    """Write `azureProfile.json` with a UTF-8 BOM, as the Azure CLI does."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "azureProfile.json"
    profile = {
        "installationId": "00000000-0000-0000-0000-000000000000",
        "subscriptions": subscriptions,
    }
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8-sig")
    return path


def write_az_login(config_dir: Path, logins: list[Login], *, default: Login) -> None:
    """A config directory after `logins`, with `default`'s subscription current."""
    write_token_cache(config_dir, logins)
    write_profile(
        config_dir,
        [
            subscription(login.username, login.tenant_id, is_default=login is default)
            for login in logins
        ],
    )
