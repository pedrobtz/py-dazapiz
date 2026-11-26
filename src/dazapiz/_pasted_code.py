"""httr2's pasted-code sign-in for a non-localhost redirect URI (design §4.3.3)."""

from __future__ import annotations

import base64
import binascii
import json
import re
import warnings
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError

from . import _session
from ._json import json_object

__all__ = ["is_localhost", "parse_reply", "request_token_by_pasted_code"]

CODE_PROMPT = "Enter authorization code or URL: "
STATE_PROMPT = "Enter state parameter: "

_LOCALHOSTS = frozenset({"localhost", "127.0.0.1"})  # httr2's normalize_redirect_uri()
_URL = re.compile(r"^https?://")  # httr2's is_string_url()


def is_localhost(redirect_uri: str) -> bool:
    """Whether httr2 would listen locally for `redirect_uri`."""
    return urlsplit(redirect_uri).hostname in _LOCALHOSTS


def _base64_json(text: str) -> dict[str, Any] | None:
    # httr2's is_base64_json(): the reply decodes to JSON. Only an object is
    # taken for this form, so a bare code that happens to decode stays a code.
    compact = text.replace("-", "+").replace("_", "/")
    try:
        raw = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=True)
        value = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError):
        return None
    return json_object(value)


def _scalar(value: object) -> object:
    # jsonlite::toJSON() writes every value as a one-element array.
    if isinstance(value, list):
        items = cast("list[object]", value)
        return items[0] if len(items) == 1 else items
    return value


def parse_reply(reply: str, read_state: Callable[[], str]) -> dict[str, Any]:
    """Turn what the user pasted into the auth response MSAL redeems.

    The three forms of httr2 1.3.0's `oauth_flow_auth_code_read()`: the full
    callback URL, base64-encoded JSON with `code` and `state`, or the bare
    code, after which `read_state()` is asked for the state. The state is not
    compared here: MSAL's `acquire_token_by_auth_code_flow()` checks it.
    """
    text = reply.strip()
    if not text:
        raise ClientAuthenticationError(message="Authentication failed: nothing was pasted.")

    if _URL.match(text):
        response = dict(parse_qsl(urlsplit(text).query))
        if "error" in response:
            description = response.get("error_description")
            raise ClientAuthenticationError(
                message=f"Authentication failed: {response['error']}"
                + (f": {description}" if description else "")
            )
        form = "callback URL"
    elif (decoded := _base64_json(text)) is not None:
        response = {k: _scalar(v) for k, v in decoded.items()}
        form = "base64 JSON"
    else:
        state = read_state().strip()
        if not state:
            raise ClientAuthenticationError(
                message="Authentication failed: no state parameter was entered."
            )
        response = {"code": text, "state": state}
        form = "code"

    if not (isinstance(response.get("code"), str) and response["code"]):
        raise ClientAuthenticationError(
            message=f"Authentication failed: the pasted {form} holds no authorization code."
        )
    if not isinstance(response.get("state"), str):
        raise ClientAuthenticationError(
            message=f"Authentication failed: the pasted {form} holds no state parameter."
        )
    return response


def request_token_by_pasted_code(
    app: Any,
    scopes: list[str],
    *,
    redirect_uri: str,
    login_hint: str | None,
    claims: str | None,
) -> dict[str, Any]:
    """Sign in through a callback page, as httr2 does: print, paste, redeem.

    Wraps MSAL's `initiate_auth_code_flow()` (PKCE, state, nonce) and
    `acquire_token_by_auth_code_flow()` (state check and redemption) on the
    credential's own MSAL app, so the result lands in its cache.
    """
    if not _session.is_interactive():
        raise CredentialUnavailableError(
            message="Signing in through a callback page needs an interactive session "
            "(a terminal or a notebook kernel) to paste the code into."
        )
    with warnings.catch_warnings():
        # MSAL recommends form_post; the pasted flow needs the code in the callback
        # page's URL, so the warning would only tell the user about dazapiz's choice.
        warnings.filterwarnings("ignore", message="response_mode='form_post' is recommended")
        flow = app.initiate_auth_code_flow(
            scopes,
            redirect_uri=redirect_uri,
            response_mode="query",
            prompt="select_account",
            login_hint=login_hint,
            claims_challenge=claims,
        )
    if "auth_uri" not in flow:
        raise CredentialUnavailableError(message="Failed to begin authentication flow")

    print(f"Open this URL in a browser to sign in:\n\n{flow['auth_uri']}\n", flush=True)
    try:
        response = parse_reply(input(CODE_PROMPT), lambda: input(STATE_PROMPT))
    except EOFError:
        raise CredentialUnavailableError(
            message="Signing in through a callback page: the input closed before a code was pasted."
        ) from None

    try:
        return app.acquire_token_by_auth_code_flow(
            flow, response, scopes=scopes, claims_challenge=claims
        )
    except ValueError as ex:  # MSAL's state mismatch and other client-side checks
        raise ClientAuthenticationError(message=f"Authentication failed: {ex}") from ex
