"""`ApiClient`, ported from `azr::api_client` on httpx (design §4.1)."""

from __future__ import annotations

import email.utils
import json as jsonlib
import logging
import random
import string
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Generator, Mapping
from typing import Any, ClassVar
from urllib.parse import quote

import httpx
from azure.core.credentials import AccessToken, TokenCredential
from rich.logging import RichHandler
from rich.markup import escape

from ._app_credential import app_credential
from .errors import ApiError

__all__ = ["ApiClient", "BearerAuth", "backoff_default"]

logger = logging.getLogger("dazure.http")

# A token is renewed this many seconds before it expires.
_EXPIRY_MARGIN = 300
# httr2's default transient statuses, which `azr` retries.
_TRANSIENT = frozenset({429, 503})
# Failures where the request never reached the server, so resending is safe.
# A read timeout is not one: the server may have acted (design §4.1).
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
_START = "dazure.start"
# azr's cli alert symbols.
_INFO = "\N{INFORMATION SOURCE}"

# Patched by the tests so retries take no time and the backoff is known.
_sleep = time.sleep
_uniform = random.uniform
_now = time.time  # token expiry
_clock = time.perf_counter  # request timing


def _transport() -> httpx.BaseTransport | None:
    """The transport the client sends through; None is httpx's own (patched by tests)."""
    return None


def backoff_default(attempt: int, max_time: float = 60.0, b: float = 2.5) -> float:
    """`azr`'s `backoff_default()`: uniform in [1, b**attempt], capped at `max_time`, 0.1 s."""
    return round(min(_uniform(1.0, b**attempt), max_time), 1)


class BearerAuth(httpx.Auth):
    """Sets `Authorization: Bearer ...` from `credential.get_token(scope)`.

    The `AccessToken` is kept until five minutes before `expires_on`. A 401
    is not replayed (`get_token()` has no force-refresh, so a replay would
    send the same token); the token is dropped so the next request asks the
    credential afresh.
    """

    def __init__(self, credential: TokenCredential, scope: str) -> None:
        self.credential = credential
        self.scope = scope
        self._token: AccessToken | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"BearerAuth(credential={type(self.credential).__name__}, scope={self.scope!r})"

    def _bearer(self) -> str:
        with self._lock:
            token = self._token
            if token is None or token.expires_on - _EXPIRY_MARGIN <= _now():
                token = self._token = self.credential.get_token(self.scope)
            return token.token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._bearer()}"
        response = yield request
        if response.status_code == 401:
            with self._lock:
                self._token = None


class ApiClient:
    """A client for one REST API, meant to be subclassed once per API.

    The class attributes say where the API is and where its credentials come
    from; `__init__` arguments override them per instance. The credential is
    the `credential` argument, else `app_credential()` with the class's
    variable names and `mode` when `client_id_env` and `client_secret_env`
    are set, else none (requests go unauthenticated). Wraps one
    `httpx.Client`; also a context manager.
    """

    host_url: ClassVar[str | None] = None
    scope: ClassVar[str | None] = None
    client_id_env: ClassVar[str | None] = None
    client_secret_env: ClassVar[str | None] = None
    tenant_id_env: ClassVar[str] = "AZURE_TENANT_ID"
    mode: ClassVar[str | None] = None

    def __init__(
        self,
        host_url: str | None = None,
        credential: TokenCredential | None = None,
        scope: str | None = None,
        *,
        timeout: float = 60,
        connect_timeout: float = 30,
        max_tries: int = 5,
        verbose: bool = False,
        response_handler: Callable[[Any], Any] | None = None,
    ) -> None:
        host = host_url if host_url is not None else type(self).host_url
        if not isinstance(host, str) or not host:
            raise ValueError(
                "host_url must be a non-empty string, as an argument or class attribute."
            )
        if not isinstance(max_tries, int) or max_tries < 1:
            raise ValueError("max_tries must be an integer >= 1.")
        self._host_url = host
        self._scope = scope or type(self).scope or f"{host.rstrip('/')}/.default"
        self._max_tries = max_tries
        self._verbose = bool(verbose)
        self._response_handler = response_handler
        if self._verbose:
            _enable_verbose()

        cls = type(self)
        if credential is None and cls.client_id_env and cls.client_secret_env:
            credential = app_credential(
                cls.client_id_env,
                cls.client_secret_env,
                tenant_id_env=cls.tenant_id_env,
                mode=cls.mode,
            )
        self._credential = credential
        auth = BearerAuth(credential, self._scope) if credential is not None else None
        hooks = {"request": [_log_request], "response": [_log_response]} if self._verbose else {}
        self._http = httpx.Client(
            base_url=host,
            auth=auth,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            event_hooks=hooks,
            transport=_transport(),
        )

    def __repr__(self) -> str:
        cred = type(self._credential).__name__ if self._credential is not None else None
        return f"{type(self).__name__}(host_url={self._host_url!r}, credential={cred})"

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying `httpx.Client`."""
        self._http.close()

    def fetch(
        self,
        path: str,
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,
        **path_params: str,
    ) -> Any:
        """Send one request to `path` under the host URL and return the parsed body.

        `{name}` placeholders in `path` are filled from `path_params`,
        URL-encoded; a missing or unused parameter is a `ValueError`. 429, 503
        and connection failures are retried up to `max_tries` attempts,
        waiting `Retry-After` or `backoff_default()`. The body is parsed by
        `content_type`, else the response's: JSON to Python objects, XML to an
        `ElementTree.Element`, anything else to `str`, an empty body to `None`;
        a non-empty result goes through `response_handler`. A non-2xx response
        raises `ApiError`.
        """
        url = _fill_path(path, path_params)
        method = method.upper()
        response = self._send(method, url, params=query, json=json, headers=headers)
        if not response.is_success:
            raise ApiError(_error_message(response), request=response.request, response=response)
        result = _parse(response, content_type)
        if result is not None and self._response_handler is not None:
            result = self._response_handler(result)
        return result

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.request(method, url, **kwargs)
            except _CONNECTION_ERRORS:
                if attempt >= self._max_tries:
                    raise
                wait = backoff_default(attempt)
            else:
                if response.status_code not in _TRANSIENT or attempt >= self._max_tries:
                    return response
                wait = _retry_after(response)
                if wait is None:
                    wait = backoff_default(attempt)
            logger.warning(
                "[yellow]⚠ Request failed. Retrying in %s secs. (attempt %d of %d).[/yellow]",
                _number(wait),
                attempt,
                self._max_tries,
            )
            _sleep(wait)


def _fill_path(path: str, params: Mapping[str, Any]) -> str:
    names = {name for _, name, _, _ in string.Formatter().parse(path) if name is not None}
    if "" in names or any(not n.isidentifier() for n in names):
        raise ValueError(f"Path placeholders must be names, as in '{{name}}': {path!r}")
    missing, unused = sorted(names - params.keys()), sorted(params.keys() - names)
    if missing:
        raise ValueError(f"Missing path parameter(s) {', '.join(missing)} for {path!r}.")
    if unused:
        raise ValueError(f"Unused path parameter(s) {', '.join(unused)} for {path!r}.")
    return path.format(**{k: quote(str(v), safe="") for k, v in params.items()})


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds, as delay-seconds or an HTTP date; None if absent or invalid."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - time.time()
    return max(seconds, 0.0) if seconds == seconds else None  # NaN is invalid


def _media_type(response: httpx.Response, content_type: str | None) -> str:
    value = content_type if content_type is not None else response.headers.get("content-type", "")
    return value.split(";", 1)[0].strip().lower()


def _parse(response: httpx.Response, content_type: str | None) -> Any:
    if not response.content:
        return None
    media = _media_type(response, content_type)
    if media == "application/json":
        return response.json()
    if media == "application/xml":
        return ET.fromstring(response.content)
    return response.text


def _error_message(response: httpx.Response) -> str:
    request = response.request
    message = (
        f"{request.method} {request.url} failed: "
        f"HTTP {response.status_code} {response.reason_phrase}".rstrip()
    )
    body = response.text
    return f"{message}\n{body}" if body else message


# Logging in azr's format (design §4.1). The hooks never log headers.


def _enable_verbose() -> None:
    if not logger.handlers:
        logger.addHandler(
            RichHandler(markup=True, show_time=False, show_level=False, show_path=False)
        )
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)


def _number(x: float) -> str:
    return f"{x:.3g}"


def _pretty_json(content: bytes) -> str:
    try:
        return jsonlib.dumps(jsonlib.loads(content), indent=2, ensure_ascii=False)
    except ValueError:
        return content.decode("utf-8", "replace")


def _log_request(request: httpx.Request) -> None:
    request.extensions[_START] = _clock()
    logger.info(f"{_INFO} >>> %s %s", request.method, escape(str(request.url)))
    content = request.content
    if content and request.headers.get("content-type", "").startswith("application/json"):
        logger.info(f"{_INFO} >>> body:")
        logger.info("%s", escape(_pretty_json(content)))


def _log_response(response: httpx.Response) -> None:
    response.read()
    start = response.request.extensions.get(_START)
    elapsed = _number(_clock() - start) if start is not None else "???"
    size = f"{len(response.content) / 1024:.2f}"
    line = f"<<< status = {response.status_code} | time = {elapsed} secs. | size = {size} Kb"
    if response.is_success:
        logger.info("[green]✔ %s[/green]", line)
        return
    logger.info("[red]✖ %s[/red]", line)
    if response.content:
        logger.info("[red]✖ <<< body:[/red]")
        body = response.content
        if _media_type(response, None) == "application/json":
            text = _pretty_json(body)
        else:
            text = response.text
        logger.info("%s", escape(text))
