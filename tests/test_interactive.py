"""The interactive credentials and their persisted-cache lookup (design §4.3.2).

No test touches the real platform store: the `store` fixture replaces
azure-identity's private `_get_persistence()` with plain files in a temporary
directory, the unencrypted Linux layout. Whether azure-identity really writes
that layout on each OS is the manual check of design §8.2.
"""

from __future__ import annotations

import azure.identity
import azure.identity._persistent_cache as persistent_cache
import msal_extensions
import pytest
from azure.identity import AuthenticationRecord, TokenCachePersistenceOptions
from helpers import Login, token_cache

from dazure import (
    AZURE_CLI_CLIENT_ID,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    RefreshTokenInfo,
    RefreshTokenNotFoundError,
    SupportsRefreshToken,
)
from dazure._interactive import find_refresh_token

HOME = "11111111-1111-1111-1111-111111111111"
GUEST = "22222222-2222-2222-2222-222222222222"
OTHER_CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLASSES = [DeviceCodeCredential, InteractiveBrowserCredential]


class Store:
    """Plain-file persistences in `root`, recording how each was asked for."""

    def __init__(self, root):
        self.root = root
        self.calls: list[tuple[bool, str, str]] = []

    def get_persistence(self, allow_unencrypted, account_name, cache_name):
        self.calls.append((allow_unencrypted, account_name, cache_name))
        return msal_extensions.FilePersistence(str(self.root / cache_name))

    def write(self, cache_name: str, logins: list[Login]) -> None:
        msal_extensions.FilePersistence(str(self.root / cache_name)).save(
            token_cache(logins).serialize()
        )


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path)
    monkeypatch.setattr(persistent_cache, "_get_persistence", s.get_persistence)
    return s


def record_of(login: Login) -> AuthenticationRecord:
    return AuthenticationRecord(
        tenant_id=login.tenant_id,
        client_id=login.client_id,
        authority=login.environment,
        home_account_id=login.home_account_id,
        username=login.username,
    )


OPTIONS = TokenCachePersistenceOptions(name="dazure", allow_unencrypted_storage=True)
alice = Login("alice@contoso.com", HOME, HOME, "rt-alice", now=100)
alice_other_client = Login("alice@contoso.com", HOME, HOME, "rt-alice-other", OTHER_CLIENT, now=200)
alice_guest = Login("alice@contoso.com", HOME, GUEST, "rt-alice-guest", now=50)
bob = Login("bob@contoso.com", HOME, HOME, "rt-bob", now=300)


# The cache lookup -------------------------------------------------------------


def test_lookup_opens_the_persistences_azure_identity_opens(store):
    # Oracle: azure-identity's own `_load_persistent_cache()`, for both caches.
    for allow in (True, False):
        options = TokenCachePersistenceOptions(name="dazure", allow_unencrypted_storage=allow)
        store.calls.clear()
        persistent_cache._load_persistent_cache(options, is_cae=False)
        persistent_cache._load_persistent_cache(options, is_cae=True)
        theirs = list(store.calls)
        store.calls.clear()
        with pytest.raises(RefreshTokenNotFoundError):
            find_refresh_token(options, record_of(alice))
        assert sorted(store.calls) == sorted(theirs)
        assert {c[2] for c in theirs} == {"dazure.nocae", "dazure.cae"}


def test_lookup_selects_by_account_and_client_id(store):
    store.write(
        "dazure.nocae", [bob, alice_other_client, alice, Login("x@y.com", GUEST, GUEST, "rt-x")]
    )
    info = find_refresh_token(OPTIONS, record_of(alice))
    assert info == RefreshTokenInfo("rt-alice", AZURE_CLI_CLIENT_ID, HOME, "alice@contoso.com")
    other = find_refresh_token(OPTIONS, record_of(alice_other_client))
    assert other.token == "rt-alice-other"
    assert other.client_id == OTHER_CLIENT


def test_lookup_returns_the_records_tenant(store):
    # Refresh tokens carry no tenant: the record's is returned.
    store.write("dazure.nocae", [alice])
    info = find_refresh_token(OPTIONS, record_of(alice_guest))
    assert info.token == "rt-alice"
    assert info.tenant_id == GUEST


def test_lookup_searches_the_cae_cache(store):
    store.write("dazure.nocae", [bob])
    store.write("dazure.cae", [alice])
    assert find_refresh_token(OPTIONS, record_of(alice)).token == "rt-alice"


def test_lookup_takes_the_newest_of_both_caches(store):
    old = Login("alice@contoso.com", HOME, HOME, "rt-alice-old", now=10)
    new = Login("alice@contoso.com", HOME, HOME, "rt-alice-new", now=20)
    store.write("dazure.nocae", [old])
    store.write("dazure.cae", [new])
    assert find_refresh_token(OPTIONS, record_of(alice)).token == "rt-alice-new"
    store.write("dazure.nocae", [new])
    store.write("dazure.cae", [old])
    assert find_refresh_token(OPTIONS, record_of(alice)).token == "rt-alice-new"


def test_lookup_reads_the_callers_cache_name(store):
    store.write("mine.nocae", [alice])
    options = TokenCachePersistenceOptions(name="mine", allow_unencrypted_storage=True)
    assert find_refresh_token(options, record_of(alice)).token == "rt-alice"
    with pytest.raises(RefreshTokenNotFoundError):
        find_refresh_token(OPTIONS, record_of(alice))


@pytest.mark.parametrize("caches", [[], ["dazure.nocae"], ["dazure.nocae", "dazure.cae"]])
def test_lookup_not_found(store, caches):
    for name in caches:
        store.write(name, [bob, alice_other_client])
    with pytest.raises(RefreshTokenNotFoundError) as err:
        find_refresh_token(OPTIONS, record_of(alice))
    assert "alice@contoso.com" in str(err.value)
    assert "dazure" in str(err.value)


def test_lookup_does_not_write(store):
    store.write("dazure.nocae", [alice])
    before = {p.name: p.read_bytes() for p in store.root.iterdir()}
    find_refresh_token(OPTIONS, record_of(alice))
    assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before


# Construction and get_refresh_token() before sign-in, on every OS leg ---------


@pytest.mark.parametrize("cls", CLASSES)
def test_construction(cls, store):
    cred = cls(allow_unencrypted_storage=True)
    assert isinstance(cred, getattr(azure.identity, cls.__name__))
    assert isinstance(cred, SupportsRefreshToken)
    options = cred._cache_options
    assert isinstance(options, TokenCachePersistenceOptions)
    assert (options.name, options.allow_unencrypted_storage) == ("dazure", True)
    assert cred._client_id == AZURE_CLI_CLIENT_ID
    assert cls()._cache_options.allow_unencrypted_storage is False
    assert store.calls == []  # constructing opens no store


@pytest.mark.parametrize("cls", CLASSES)
def test_construction_keeps_the_callers_options(cls, store):
    mine = TokenCachePersistenceOptions(name="mine")
    assert cls(cache_persistence_options=mine)._cache_options is mine
    with pytest.raises(ValueError, match="allow_unencrypted_storage"):
        cls(cache_persistence_options=mine, allow_unencrypted_storage=True)


@pytest.mark.parametrize("cls", CLASSES)
def test_get_refresh_token_signs_in_first(cls, store, monkeypatch):
    # The sign-in itself is replaced: it writes the cache as azure-identity would
    # and returns what msal returns; authenticate() and the record are the parent's.
    signed_in = []

    def request_token(*scopes, **kwargs):
        signed_in.append(scopes)
        store.write("dazure.nocae", [bob, alice])
        return alice.token_result()

    cred = cls(allow_unencrypted_storage=True)
    monkeypatch.setattr(cred, "_request_token", request_token)
    info = cred.get_refresh_token()
    assert info == RefreshTokenInfo("rt-alice", AZURE_CLI_CLIENT_ID, HOME, "alice@contoso.com")
    assert signed_in == [("https://management.core.windows.net//.default",)]
    assert cred.get_refresh_token() == info
    assert len(signed_in) == 1  # the second call does not sign in again


@pytest.mark.parametrize("cls", CLASSES)
def test_get_refresh_token_with_a_record_does_not_sign_in(cls, store, monkeypatch):
    store.write("dazure.nocae", [alice_guest])
    cred = cls(authentication_record=record_of(alice_guest), allow_unencrypted_storage=True)
    monkeypatch.setattr(cred, "_request_token", lambda *a, **k: pytest.fail("signed in"))
    info = cred.get_refresh_token()
    assert (info.token, info.tenant_id) == ("rt-alice-guest", GUEST)
