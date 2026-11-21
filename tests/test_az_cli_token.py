"""refresh_token_from_az_cli() against caches written by msal itself (design §4.3.1)."""

import re
import sys
from pathlib import Path

import pytest
from helpers import Login, subscription, write_az_login, write_profile, write_token_cache

import dazure._az_cli_token
from dazure import (
    AZURE_CLI_CLIENT_ID,
    DazureError,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    UnsupportedPlatformError,
    refresh_token_from_az_cli,
)

CONTOSO = "11111111-1111-1111-1111-111111111111"
FABRIKAM = "22222222-2222-2222-2222-222222222222"

ALICE = Login("alice@contoso.com", CONTOSO, CONTOSO, "rt-alice")
BOB = Login("bob@fabrikam.com", FABRIKAM, FABRIKAM, "rt-bob")
BOB_GUEST = Login("bob@fabrikam.com", FABRIKAM, CONTOSO, "rt-bob-guest")


@pytest.fixture(autouse=True)
def lookup_runs_here(monkeypatch):
    """Run the lookup on every OS leg: on Windows only the refusal tests see Windows."""
    monkeypatch.delenv("AZURE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(dazure._az_cli_token, "_is_windows", lambda: False)


def lookup(config_dir, **kwargs):
    return refresh_token_from_az_cli(config_dir=config_dir, **kwargs)


# Cache entry choice ---------------------------------------------------------


def test_one_account(tmp_path):
    write_az_login(tmp_path, [ALICE], default=ALICE)
    info = lookup(tmp_path)
    assert info == RefreshTokenInfo("rt-alice", AZURE_CLI_CLIENT_ID, CONTOSO, "alice@contoso.com")


def test_work_and_guest_accounts(tmp_path):
    # Alice's work account and Bob's guest account in Contoso, Bob current.
    write_az_login(tmp_path, [ALICE, BOB_GUEST], default=BOB_GUEST)
    info = lookup(tmp_path)
    assert (info.token, info.tenant_id, info.username) == (
        "rt-bob-guest",
        CONTOSO,
        "bob@fabrikam.com",
    )

    write_az_login(tmp_path, [ALICE, BOB_GUEST], default=ALICE)
    assert lookup(tmp_path).token == "rt-alice"


def test_one_person_in_several_tenants(tmp_path):
    # Bob signs in to his home tenant, then as a guest in Contoso: one
    # home_account_id, one refresh token (rotated), two tenants.
    write_az_login(tmp_path, [BOB, BOB_GUEST], default=BOB)
    info = lookup(tmp_path)
    # Refresh tokens carry no tenant: the tenant comes from the profile.
    assert (info.token, info.tenant_id) == ("rt-bob-guest", FABRIKAM)

    write_az_login(tmp_path, [BOB, BOB_GUEST], default=BOB_GUEST)
    info = lookup(tmp_path)
    assert (info.token, info.tenant_id) == ("rt-bob-guest", CONTOSO)


def test_newest_of_several_refresh_tokens(tmp_path):
    older = Login(ALICE.username, CONTOSO, CONTOSO, "rt-old", scope=("a/.default",), now=1000)
    newer = Login(ALICE.username, CONTOSO, CONTOSO, "rt-new", scope=("b/.default",), now=2000)
    write_token_cache(tmp_path, [newer, older])
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    assert lookup(tmp_path).token == "rt-new"


def test_token_for_another_client_id_is_not_taken(tmp_path):
    other = Login(ALICE.username, CONTOSO, CONTOSO, "rt-other-app", client_id="other-client")
    write_az_login(tmp_path, [other], default=other)
    with pytest.raises(RefreshTokenNotFoundError, match=re.escape("alice@contoso.com")):
        lookup(tmp_path)

    write_token_cache(tmp_path, [other, ALICE])
    assert lookup(tmp_path).token == "rt-alice"


def test_username_is_case_insensitive_as_in_msal(tmp_path):
    write_token_cache(tmp_path, [ALICE])
    write_profile(tmp_path, [subscription("Alice@Contoso.com", CONTOSO, is_default=True)])
    assert lookup(tmp_path).token == "rt-alice"


def test_username_override(tmp_path):
    write_az_login(tmp_path, [ALICE, BOB], default=ALICE)
    info = lookup(tmp_path, username="bob@fabrikam.com")
    # The tenant is that of a subscription of Bob's, not of the default one.
    assert (info.token, info.tenant_id, info.username) == ("rt-bob", FABRIKAM, "bob@fabrikam.com")


def test_username_override_prefers_the_default_subscription(tmp_path):
    write_token_cache(tmp_path, [BOB, BOB_GUEST])
    write_profile(
        tmp_path,
        [
            subscription(BOB.username, FABRIKAM),
            subscription(BOB.username, CONTOSO, is_default=True),
        ],
    )
    assert lookup(tmp_path, username=BOB.username.upper()).tenant_id == CONTOSO


def test_username_override_without_a_subscription(tmp_path):
    write_token_cache(tmp_path, [ALICE, BOB])
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    with pytest.raises(RefreshTokenNotFoundError, match=re.escape("bob@fabrikam.com")) as err:
        lookup(tmp_path, username="bob@fabrikam.com")
    assert "azureProfile.json" in str(err.value)


def test_tenant_id_override(tmp_path):
    write_az_login(tmp_path, [BOB, BOB_GUEST], default=BOB)
    info = lookup(tmp_path, tenant_id="33333333-3333-3333-3333-333333333333")
    assert (info.username, info.tenant_id) == (BOB.username, "33333333-3333-3333-3333-333333333333")


def test_both_overrides_need_no_profile(tmp_path):
    write_token_cache(tmp_path, [ALICE])
    info = lookup(tmp_path, username=ALICE.username, tenant_id=FABRIKAM)
    assert (info.token, info.tenant_id) == ("rt-alice", FABRIKAM)


def test_azure_config_dir(tmp_path, monkeypatch):
    from_env = tmp_path / "from-env"
    write_az_login(from_env, [ALICE], default=ALICE)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(from_env))
    assert refresh_token_from_az_cli().token == "rt-alice"

    # config_dir beats the variable.
    given = tmp_path / "given"
    write_az_login(given, [BOB], default=BOB)
    assert refresh_token_from_az_cli(config_dir=given).token == "rt-bob"
    assert refresh_token_from_az_cli(config_dir=str(given)).token == "rt-bob"


def test_home_azure_is_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("AZURE_CONFIG_DIR", "")  # empty is unset
    write_az_login(tmp_path / ".azure", [ALICE], default=ALICE)
    assert refresh_token_from_az_cli().token == "rt-alice"


def test_profile_without_bom(tmp_path):
    write_az_login(tmp_path, [ALICE], default=ALICE)
    path = tmp_path / "azureProfile.json"
    path.write_bytes(path.read_bytes().removeprefix(b"\xef\xbb\xbf"))
    assert lookup(tmp_path).token == "rt-alice"


def test_cache_is_only_read(tmp_path):
    write_az_login(tmp_path, [ALICE], default=ALICE)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    lookup(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


# Refusals ------------------------------------------------------------------


def test_no_login_at_all(tmp_path):
    with pytest.raises(RefreshTokenNotFoundError, match="az login") as err:
        lookup(tmp_path)
    assert str(Path(tmp_path) / "azureProfile.json") in str(err.value)


def test_no_default_subscription(tmp_path):
    # After `az logout` the profile stays, with no subscriptions.
    write_token_cache(tmp_path, [ALICE])
    write_profile(tmp_path, [])
    with pytest.raises(RefreshTokenNotFoundError, match="default subscription") as err:
        lookup(tmp_path)
    assert "azureProfile.json" in str(err.value)

    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO)])
    with pytest.raises(RefreshTokenNotFoundError, match="default subscription"):
        lookup(tmp_path)


@pytest.mark.parametrize(
    "profile",
    [
        [1, 2],  # not an object
        {"subscriptions": "nope"},
        {"subscriptions": [{"isDefault": True, "user": {"name": 7}, "tenantId": CONTOSO}]},
        {"subscriptions": [{"isDefault": True, "user": "alice", "tenantId": CONTOSO}]},
        {"subscriptions": [{"isDefault": True, "user": {"name": "alice"}, "tenantId": 5}]},
    ],
    ids=["array", "subscriptions-not-a-list", "name-not-str", "user-not-object", "tenant-not-str"],
)
def test_malformed_profile_is_no_default_subscription(tmp_path, profile):
    # (#26) A profile of the wrong shape is "no default subscription", never a
    # non-string username or tenant passed on, nor an AttributeError.
    import json

    write_token_cache(tmp_path, [ALICE])
    (tmp_path / "azureProfile.json").write_text(json.dumps(profile), encoding="utf-8-sig")
    with pytest.raises(RefreshTokenNotFoundError, match="default subscription"):
        lookup(tmp_path)


def test_override_ignores_a_non_string_tenant(tmp_path):
    # (#26) With a username given, a subscription whose tenantId is not a string is skipped.
    write_token_cache(tmp_path, [ALICE])
    sub = subscription(ALICE.username, CONTOSO, is_default=True)
    write_profile(tmp_path, [{**sub, "tenantId": 5}])
    with pytest.raises(RefreshTokenNotFoundError, match="No subscription of"):
        lookup(tmp_path, username=ALICE.username)


def test_unreadable_profile(tmp_path):
    (tmp_path / "azureProfile.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RefreshTokenNotFoundError, match=re.escape("azureProfile.json")):
        lookup(tmp_path)


def test_no_cache_file(tmp_path):
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    with pytest.raises(RefreshTokenNotFoundError, match=re.escape("msal_token_cache.json")) as err:
        lookup(tmp_path)
    assert "alice@contoso.com" in str(err.value)


def test_encrypted_cache_is_named(tmp_path):
    # `az config set core.encrypt_token_cache=true` writes msal_token_cache.bin.
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    (tmp_path / "msal_token_cache.bin").write_bytes(b"\x00encrypted")
    with pytest.raises(RefreshTokenNotFoundError, match="encrypt_token_cache") as err:
        lookup(tmp_path)
    assert "msal_token_cache.bin" in str(err.value)


def test_unreadable_cache(tmp_path):
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    (tmp_path / "msal_token_cache.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RefreshTokenNotFoundError, match=re.escape("msal_token_cache.json")):
        lookup(tmp_path)


def test_no_matching_token(tmp_path):
    write_token_cache(tmp_path, [BOB])
    path = write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    with pytest.raises(RefreshTokenNotFoundError) as err:
        lookup(tmp_path)
    message = str(err.value)
    assert "alice@contoso.com" in message
    assert str(path.parent / "msal_token_cache.json") in message
    assert "rt-bob" not in message


def test_errors_derive_from_dazure_error():
    assert issubclass(RefreshTokenNotFoundError, DazureError)
    assert issubclass(UnsupportedPlatformError, DazureError)


def test_windows_refused(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real platform check
    write_az_login(tmp_path, [ALICE], default=ALICE)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(UnsupportedPlatformError, match="AZURE_REFRESH_TOKEN"):
        refresh_token_from_az_cli(config_dir=tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="the real Windows leg")
def test_windows_refused_on_windows(tmp_path, monkeypatch):
    monkeypatch.undo()  # nothing patched: this is Windows
    write_az_login(tmp_path, [ALICE], default=ALICE)
    with pytest.raises(UnsupportedPlatformError, match="DeviceCodeCredential"):
        refresh_token_from_az_cli(config_dir=tmp_path)


def test_cache_that_is_not_utf8(tmp_path):
    write_profile(tmp_path, [subscription(ALICE.username, CONTOSO, is_default=True)])
    (tmp_path / "msal_token_cache.json").write_bytes(b'{"RefreshToken": "\xff\xfe"}')
    with pytest.raises(RefreshTokenNotFoundError, match="could not be read") as err:
        lookup(tmp_path)
    assert "UnicodeDecodeError" in str(err.value)
