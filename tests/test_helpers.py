"""The az login writer in `helpers.py`: a wrong helper would turn failures into passes."""

import json

import msal
from helpers import Login, subscription, write_profile, write_token_cache

from dazapiz import AZURE_CLI_CLIENT_ID

ALICE = Login("alice@contoso.com", "contoso-tid", "contoso-tid", "rt-alice")
ALICE_GUEST = Login("alice@contoso.com", "contoso-tid", "fabrikam-tid", "rt-alice-2")


def test_cache_entries_are_msal_s_own(tmp_path):
    path = write_token_cache(tmp_path, [ALICE, ALICE_GUEST])
    raw = json.loads(path.read_text(encoding="utf-8"))

    # msal derived home_account_id from client_info: <uid>.<home tenant>
    accounts = list(raw["Account"].values())
    assert {a["home_account_id"] for a in accounts} == {ALICE.home_account_id}
    assert ALICE.home_account_id.endswith(".contoso-tid")
    assert {a["realm"] for a in accounts} == {"contoso-tid", "fabrikam-tid"}
    assert {a["username"] for a in accounts} == {"alice@contoso.com"}

    # One refresh token per person and client: the second login rotated it.
    rts = list(raw["RefreshToken"].values())
    assert len(rts) == 1
    assert rts[0]["secret"] == "rt-alice-2"
    assert rts[0]["client_id"] == AZURE_CLI_CLIENT_ID
    assert rts[0]["home_account_id"] == ALICE.home_account_id
    assert rts[0]["environment"] == "login.microsoftonline.com"


def test_cache_round_trips_through_msal(tmp_path):
    path = write_token_cache(tmp_path, [ALICE])
    cache = msal.SerializableTokenCache()
    cache.deserialize(path.read_text(encoding="utf-8"))
    found = list(
        cache.search(cache.CredentialType.REFRESH_TOKEN, query={"client_id": AZURE_CLI_CLIENT_ID})
    )
    assert [rt["secret"] for rt in found] == ["rt-alice"]


def test_profile_has_a_bom_and_one_default(tmp_path):
    path = write_profile(
        tmp_path,
        [subscription("a@x", "t1"), subscription("b@x", "t2", is_default=True)],
    )
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    profile = json.loads(path.read_text(encoding="utf-8-sig"))
    default = [s for s in profile["subscriptions"] if s["isDefault"]]
    assert [(s["user"]["name"], s["tenantId"]) for s in default] == [("b@x", "t2")]
