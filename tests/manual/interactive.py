"""The interactive items of the manual checklist, run by hand (README.md here).

    uv run python tests/manual/interactive.py device-code [--unencrypted]
    uv run python tests/manual/interactive.py browser [--unencrypted]
    uv run python tests/manual/interactive.py pasted-code [--unencrypted]
    uv run python tests/manual/interactive.py az-helpers

Each prints one line per step, `PASS` or `FAIL`, and exits non-zero on the
first failure. No token or secret is ever printed: only lengths, client
IDs, tenants and usernames. Not a pytest module; nothing runs on import.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Run as a script, its directory is first on sys.path.
from live_helpers import ARM_SCOPE, jwt_claims


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}", flush=True)
    if not ok:
        sys.exit(1)


def _credential_kwargs(kind: str) -> dict:
    if kind != "pasted-code":
        return {}
    names = ("DAZURE_TEST_APP_CLIENT_ID", "DAZURE_TEST_APP_TENANT_ID", "DAZURE_TEST_REDIRECT_URI")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"set {', '.join(missing)} (tests/manual/README.md)")
    client_id, tenant_id, redirect_uri = (os.environ[n] for n in names)
    return {"client_id": client_id, "tenant_id": tenant_id, "redirect_uri": redirect_uri}


def sign_in(kind: str, unencrypted: bool) -> None:
    """Items 2 and 3: real sign-in, the persisted cache read back, a silent second token."""
    from azure.identity import AuthenticationRequiredError

    import dazure

    cls = (
        dazure.DeviceCodeCredential
        if kind == "device-code"
        else dazure.InteractiveBrowserCredential
    )
    kwargs = _credential_kwargs(kind)
    credential = cls(allow_unencrypted_storage=unencrypted, **kwargs)

    record = credential.authenticate(scopes=[ARM_SCOPE])
    step("sign-in", bool(record.username), f"{record.username} in tenant {record.tenant_id}")

    info = credential.get_refresh_token()
    step(
        "get_refresh_token() finds the token azure-identity persisted",
        info.client_id == record.client_id
        and (info.username or "").lower() == record.username.lower(),
        f"client {info.client_id}, tenant {info.tenant_id}, token of {len(info.token)} chars",
    )
    step("the refresh token is redacted in repr", info.token not in repr(info))

    access = dazure.RefreshTokenCredential(info).get_token(ARM_SCOPE)
    claims = jwt_claims(access.token)
    step(
        "RefreshTokenCredential redeems it",
        access.expires_on > time.time() and claims.get("tid") == record.tenant_id,
        f"ARM token for tenant {claims.get('tid')}",
    )

    silent = cls(
        allow_unencrypted_storage=unencrypted,
        authentication_record=record,
        disable_automatic_authentication=True,
        **kwargs,
    )
    try:
        silent.get_token(ARM_SCOPE)
        step("a second credential gets a token silently from the persisted cache", True)
    except AuthenticationRequiredError as err:
        step("a second credential gets a token silently from the persisted cache", False, str(err))


def az_helpers() -> None:
    """Item 5: az_login() with a device code, az_account_show(), az_logout()."""
    import dazure

    account = dazure.az_login(force=True)
    step("az_login(force=True) by device code", bool(account.get("id")), account["user"]["name"])
    shown = dazure.az_account_show()
    step("az_account_show() is the account az_login() returned", shown["id"] == account["id"])
    step("az_is_login() is True", dazure.az_is_login() is True)
    dazure.az_logout()
    step("az_logout(); az_is_login() is False", dazure.az_is_login() is False)
    try:
        dazure.az_account_show()
        step("az_account_show() after logout raises AzCliNotLoggedInError", False)
    except dazure.AzCliNotLoggedInError:
        step("az_account_show() after logout raises AzCliNotLoggedInError", True)
    print("Log in again with `az login` before the other items.", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("item", choices=["device-code", "browser", "pasted-code", "az-helpers"])
    parser.add_argument(
        "--unencrypted",
        action="store_true",
        help="allow_unencrypted_storage=True (headless Linux without libsecret)",
    )
    args = parser.parse_args(argv)
    if args.item == "az-helpers":
        az_helpers()
    else:
        sign_in(args.item, args.unencrypted)


if __name__ == "__main__":
    main()
