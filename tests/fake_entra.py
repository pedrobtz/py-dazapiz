"""A fake Entra ID behind msal's `http_client` hook: the HTTP boundary only.

A real `msal.PublicClientApplication` built with `http_client=FakeEntra(...)`
and `instance_discovery=False` makes exactly two kinds of request: the
tenant's OpenID configuration (GET) and the token endpoint (POST). Both are
answered here; anything else fails the test, so nothing leaves the machine.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_DISCOVERY = "/v2.0/.well-known/openid-configuration"


@dataclass
class FakeResponse:
    """The response shape msal reads: status, text, headers, raise_for_status()."""

    status_code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeEntra:
    """Answers msal's discovery GETs and token POSTs; `token` builds each token reply.

    `token` receives the POSTed form and returns the JSON body. `posts` records
    every form posted, `gets` every URL fetched.
    """

    token: Callable[[dict[str, Any]], dict[str, Any]]
    gets: list[str] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)

    def get(self, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> FakeResponse:
        self.gets.append(url)
        parts = urlsplit(url)
        assert parts.path.endswith(_DISCOVERY), f"unexpected GET {url}"
        base = f"https://{parts.netloc}{parts.path[: -len(_DISCOVERY)]}"
        config = {
            "issuer": f"{base}/v2.0",
            "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
            "token_endpoint": f"{base}/oauth2/v2.0/token",
            "device_authorization_endpoint": f"{base}/oauth2/v2.0/devicecode",
            "end_session_endpoint": f"{base}/oauth2/v2.0/logout",
        }
        return FakeResponse(200, json.dumps(config))

    def post(
        self, url: str, params: Any = None, data: Any = None, headers: Any = None, **kwargs: Any
    ) -> FakeResponse:
        assert urlsplit(url).path.endswith("/oauth2/v2.0/token"), f"unexpected POST {url}"
        form = dict(data or {})
        self.posts.append(form)
        return FakeResponse(200, json.dumps(self.token(form)))

    def close(self) -> None:
        pass
