"""The pasted-code sign-in of `InteractiveBrowserCredential` (design §4.3.3).

MSAL is never constructed (design D26): the credential's `_get_app()` returns a
fake that records the two calls the flow makes. The `real_msal` tests hand it a
real `PublicClientApplication` instead, with only its HTTP faked (`fake_entra`),
so MSAL's own state check is what runs.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import types
from urllib.parse import parse_qsl, urlsplit

import azure.identity
import msal
import pytest
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError
from fake_entra import FakeEntra
from helpers import Login

import dazapiz._session
from dazapiz import InteractiveBrowserCredential
from dazapiz._pasted_code import parse_reply
from dazapiz._session import is_interactive

TENANT = "11111111-1111-1111-1111-111111111111"
REDIRECT = "https://your-domain.example/azure-callback"


def no_state():
    pytest.fail("asked for the state")


# The reply parser -------------------------------------------------------------
#
# The three reply forms and their expected codes are copied from httr2 1.3.0:
# `oauth_flow_auth_code_read()` (R/oauth-flow-auth-code.R) and its tests in
# tests/testthat/test-oauth-flow-auth-code.R, "URL embedding authorisation code
# and state can be input manually", "JSON-encoded authorisation codes can be
# input manually" and "bare authorisation codes can be input manually". httr2
# checks the state itself; here the state goes back to MSAL, which checks it.


def test_reply_callback_url():
    # httr2: readline() returns "https://x.com?code=code&state=state".
    reply = parse_reply("https://x.com?code=code&state=state", no_state)
    assert reply == {"code": "code", "state": "state"}


def test_reply_base64_json():
    # httr2: openssl::base64_encode(jsonlite::toJSON(list(state = "state", code = "code"))),
    # which is this string: jsonlite writes each value as a one-element array.
    encoded = "eyJzdGF0ZSI6WyJzdGF0ZSJdLCJjb2RlIjpbImNvZGUiXX0="
    assert parse_reply(encoded, no_state) == {"code": "code", "state": "state"}


def test_reply_base64_json_with_scalars():
    # The same with plain strings, as a page with jsonlite's auto_unbox would show.
    encoded = base64.b64encode(json.dumps({"state": "state", "code": "code"}).encode()).decode()
    assert parse_reply(encoded, no_state) == {"code": "code", "state": "state"}


def test_reply_bare_code_then_state():
    # httr2: the first readline() returns "zyx987", the second the state.
    asked = []

    def read_state():
        asked.append(True)
        return "  st4te-from-the-page \n"

    assert parse_reply("zyx987", read_state) == {"code": "zyx987", "state": "st4te-from-the-page"}
    assert asked == [True]


def test_reply_is_trimmed():
    # httr2 trims the line with trimws().
    reply = parse_reply("  https://x.com?code=code&state=state\n", no_state)
    assert reply == {"code": "code", "state": "state"}


def test_reply_url_keeps_every_query_parameter():
    # What a local listener would hand MSAL: the whole query.
    url = "https://x.com/cb?code=c&state=s&session_state=ss&client_info=ci"
    assert parse_reply(url, no_state) == {
        "code": "c",
        "state": "s",
        "session_state": "ss",
        "client_info": "ci",
    }


def test_reply_error_query():
    url = "https://x.com/cb?error=access_denied&error_description=The+user+cancelled&state=s"
    with pytest.raises(ClientAuthenticationError) as err:
        parse_reply(url, no_state)
    assert "access_denied" in str(err.value)
    assert "The user cancelled" in str(err.value)


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "   ",
        "https://x.com/cb",
        "https://x.com/cb?state=s",
        "https://x.com/cb?code=&state=s",
        "https://x.com/cb?code=c",
        base64.b64encode(b'{"code": "c"}').decode(),
        base64.b64encode(b'{"state": "s"}').decode(),
        base64.b64encode(b'{"code": 1, "state": "s"}').decode(),
    ],
)
def test_reply_garbage(reply):
    with pytest.raises(ClientAuthenticationError):
        parse_reply(reply, no_state)


def test_reply_bare_code_without_state():
    with pytest.raises(ClientAuthenticationError, match="state"):
        parse_reply("zyx987", lambda: "  ")


# The redirect rule ------------------------------------------------------------


@pytest.mark.parametrize("redirect_uri", [None, "http://localhost:8400", "http://127.0.0.1:8400"])
def test_localhost_or_none_reaches_the_parent(redirect_uri, monkeypatch):
    calls = []
    monkeypatch.setattr(
        azure.identity.InteractiveBrowserCredential,
        "_request_token",
        lambda self, *scopes, **kwargs: calls.append((scopes, kwargs)) or {"parent": True},
    )
    kwargs = {} if redirect_uri is None else {"redirect_uri": redirect_uri}
    cred = InteractiveBrowserCredential(**kwargs)
    parent = azure.identity.InteractiveBrowserCredential(**kwargs)
    assert cred._parsed_url == parent._parsed_url
    assert cred._pasted_redirect_uri is None
    assert cred._request_token("User.Read", claims="c") == {"parent": True}
    assert calls == [(("User.Read",), {"claims": "c"})]


def test_localhost_without_port_is_the_parents_error():
    with pytest.raises(ValueError, match="port"):
        azure.identity.InteractiveBrowserCredential(redirect_uri="http://localhost/cb")
    with pytest.raises(ValueError, match="port"):
        InteractiveBrowserCredential(redirect_uri="http://localhost/cb")


@pytest.mark.parametrize(
    "redirect_uri",
    [
        REDIRECT,
        "https://code.example.com:8443/proxy/8080/callback",
        "http://localhost.example.com/cb",
    ],
)
def test_other_uris_reach_the_pasted_flow(redirect_uri, monkeypatch):
    monkeypatch.setattr(
        azure.identity.InteractiveBrowserCredential,
        "_request_token",
        lambda *a, **k: pytest.fail("reached the parent"),
    )
    cred = InteractiveBrowserCredential(redirect_uri=redirect_uri)
    assert cred._parsed_url is None  # the parent never saw it
    assert cred._pasted_redirect_uri == redirect_uri
    app = FakeApp()
    monkeypatch.setattr(cred, "_get_app", lambda **kwargs: app)
    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": app.callback_url())
    cred._request_token("User.Read")
    assert app.initiated[0][1]["redirect_uri"] == redirect_uri


# The flow, with the MSAL app's two methods patched ------------------------------


class FakeApp:
    """The two `msal.PublicClientApplication` methods the flow calls."""

    def __init__(self, result=None, error=None):
        self.result = result or Login("alice@contoso.com", TENANT, TENANT, "rt").token_result()
        self.error = error
        self.initiated = []
        self.redeemed = []
        self.flow = {
            "auth_uri": "https://login.microsoftonline.com/t/oauth2/v2.0/authorize"
            "?client_id=c&response_type=code&state=STATE-from-msal&code_challenge=x",
            "state": "STATE-from-msal",
            "code_verifier": "verifier",
            "nonce": "nonce",
            "scope": ["User.Read"],
        }

    def initiate_auth_code_flow(self, scopes, **kwargs):
        self.initiated.append((scopes, kwargs))
        return self.flow

    def acquire_token_by_auth_code_flow(self, auth_code_flow, auth_response, **kwargs):
        self.redeemed.append((auth_code_flow, auth_response, kwargs))
        if self.error:
            raise self.error
        return self.result

    def callback_url(self, state="STATE-from-msal"):
        return f"{REDIRECT}?code=the-code&state={state}"


@pytest.fixture
def flow(monkeypatch):
    """A pasted-mode credential on a fake app, an interactive session and a reply."""

    def make(reply, app=None, **kwargs):
        cred = InteractiveBrowserCredential(redirect_uri=REDIRECT, **kwargs)
        app = app or FakeApp()
        monkeypatch.setattr(cred, "_get_app", lambda **kw: app)
        monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: True)
        prompts = []

        def fake_input(prompt=""):
            prompts.append(prompt)
            return reply(app) if callable(reply) else reply

        monkeypatch.setattr("builtins.input", fake_input)
        return cred, app, prompts

    return make


def test_flow_prints_msals_url_and_returns_msals_result(flow, capsys):
    cred, app, prompts = flow(FakeApp.callback_url, login_hint="alice@contoso.com")
    result = cred._request_token("User.Read", claims="the-claims")
    assert result is app.result
    assert app.flow["auth_uri"] in capsys.readouterr().out
    assert app.initiated == [
        (
            ["User.Read"],
            {
                "redirect_uri": REDIRECT,
                "response_mode": "query",
                "prompt": "select_account",
                "login_hint": "alice@contoso.com",
                "claims_challenge": "the-claims",
            },
        )
    ]
    [(passed_flow, response, kwargs)] = app.redeemed
    assert passed_flow is app.flow
    assert response == {"code": "the-code", "state": "STATE-from-msal"}
    assert kwargs == {"scopes": ["User.Read"], "claims_challenge": "the-claims"}
    assert prompts == ["Enter authorization code or URL: "]


def test_flow_bare_code_asks_for_the_state(flow):
    replies = iter(["the-code", "STATE-from-msal"])
    cred, app, prompts = flow(lambda app: next(replies))
    cred._request_token("User.Read")
    assert app.redeemed[0][1] == {"code": "the-code", "state": "STATE-from-msal"}
    assert prompts == ["Enter authorization code or URL: ", "Enter state parameter: "]


def test_flow_through_get_token(flow):
    # The parent's get_token() runs the silent lookup, then this flow, then
    # builds the AuthenticationRecord from MSAL's result.
    cred, app, _ = flow(FakeApp.callback_url)
    token = cred.get_token("User.Read")
    assert token.token == app.result["access_token"]
    assert cred._auth_record.username == "alice@contoso.com"
    assert len(app.redeemed) == 1


def test_flow_msal_value_error_is_an_authentication_error(flow):
    app = FakeApp(error=ValueError("state mismatch: STATE-from-msal vs other"))
    cred, _, _ = flow(lambda app: app.callback_url(state="other"), app=app)
    with pytest.raises(ClientAuthenticationError) as err:
        cred._request_token("User.Read")
    assert not isinstance(err.value, CredentialUnavailableError)
    assert "state" in str(err.value)
    assert isinstance(err.value.__cause__, ValueError)


def test_flow_error_reply_is_an_authentication_error(flow):
    cred, app, _ = flow(f"{REDIRECT}?error=access_denied&error_description=no&state=s")
    with pytest.raises(ClientAuthenticationError, match="access_denied"):
        cred._request_token("User.Read")
    assert app.redeemed == []


def test_flow_without_an_interactive_session(flow, monkeypatch):
    cred, app, prompts = flow(FakeApp.callback_url)
    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: False)
    with pytest.raises(CredentialUnavailableError, match="interactive"):
        cred._request_token("User.Read")
    with pytest.raises(CredentialUnavailableError):
        cred.get_token("User.Read")
    assert app.initiated == []
    assert prompts == []


def test_flow_closed_input(flow, monkeypatch):
    cred, app, _ = flow(None)

    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(CredentialUnavailableError):
        cred._request_token("User.Read")
    assert app.redeemed == []


# The interactive-session check -----------------------------------------------


class Stdin:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


def fake_ipython(shell):
    module = types.ModuleType("IPython")
    module.get_ipython = lambda: shell
    return module


def test_is_interactive_tty(monkeypatch):
    monkeypatch.delitem(sys.modules, "IPython", raising=False)
    monkeypatch.setattr(sys, "stdin", Stdin(True))
    assert is_interactive() is True
    monkeypatch.setattr(sys, "stdin", Stdin(False))
    assert is_interactive() is False
    monkeypatch.setattr(sys, "stdin", None)
    assert is_interactive() is False


def test_is_interactive_notebook_kernel(monkeypatch):
    monkeypatch.setattr(sys, "stdin", Stdin(False))
    monkeypatch.setitem(
        sys.modules, "IPython", fake_ipython(types.SimpleNamespace(kernel=object()))
    )
    assert is_interactive() is True
    monkeypatch.setitem(sys.modules, "IPython", fake_ipython(types.SimpleNamespace()))
    assert is_interactive() is False
    monkeypatch.setitem(sys.modules, "IPython", fake_ipython(None))
    assert is_interactive() is False


def test_flow_msal_could_not_begin(flow, capsys):
    app = FakeApp()
    app.flow = {"error": "invalid_scope"}  # MSAL returned no auth_uri
    cred, _, prompts = flow(FakeApp.callback_url, app=app)
    with pytest.raises(CredentialUnavailableError, match="begin authentication"):
        cred._request_token("User.Read")
    assert prompts == []
    assert app.redeemed == []
    assert capsys.readouterr().out == ""


# The flow on a real msal.PublicClientApplication, faking only HTTP (#49) --------


class RealMsal:
    """A real PublicClientApplication on a FakeEntra, and the URL the user was shown."""

    def __init__(self, capsys):
        self.capsys = capsys
        self.query: dict[str, str] = {}
        self.entra = FakeEntra(token=self.token_reply)
        self.app = msal.PublicClientApplication(
            "cid",
            authority=f"https://login.microsoftonline.com/{TENANT}",
            http_client=self.entra,
            instance_discovery=False,
        )

    def read_auth_uri(self) -> None:
        """What the user does: open the printed URL, which carries state and nonce."""
        out = self.capsys.readouterr().out
        [url] = re.findall(r"https://\S+/authorize\?\S+", out)
        self.query = dict(parse_qsl(urlsplit(url).query))

    def callback_url(self, state=None):
        self.read_auth_uri()
        return f"{REDIRECT}?code=the-code&state={state or self.query['state']}"

    def token_reply(self, form):
        login = Login("alice@contoso.com", TENANT, TENANT, "rt", client_id="cid")
        claims = {**login.id_token_claims(), "nonce": self.query["nonce"]}
        part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return {**login.token_response(), "id_token": f"e30.{part}."}


# The suite turns warnings into errors, so these tests also check that MSAL's
# warning about response_mode="query" does not reach the user.


def test_real_msal_flow_with_the_right_state(flow, capsys):
    real = RealMsal(capsys)
    cred, _, _ = flow(lambda app: real.callback_url(), app=real.app)
    token = cred.get_token("User.Read")
    assert token.token == "access-rt"
    assert cred._auth_record.username == "alice@contoso.com"
    assert real.query["redirect_uri"] == REDIRECT
    [form] = real.entra.posts
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["redirect_uri"] == REDIRECT
    assert form["code_verifier"]  # PKCE, from msal's flow


def test_real_msal_flow_with_a_tampered_state(flow, capsys):
    real = RealMsal(capsys)
    cred, _, _ = flow(lambda app: real.callback_url(state="tampered"), app=real.app)
    with pytest.raises(ClientAuthenticationError) as err:
        cred._request_token("User.Read")
    assert type(err.value) is ClientAuthenticationError
    expected = f"Authentication failed: state mismatch: {real.query['state']} vs tampered"
    assert err.value.message == expected
    assert real.entra.posts == []  # refused before the code was redeemed


def test_is_interactive_when_get_ipython_raises(monkeypatch):
    def broken():
        raise RuntimeError("no shell")

    module = types.ModuleType("IPython")
    module.get_ipython = broken
    monkeypatch.setattr(sys, "stdin", Stdin(False))
    monkeypatch.setitem(sys.modules, "IPython", module)
    assert is_interactive() is False
