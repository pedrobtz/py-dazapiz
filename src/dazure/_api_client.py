"""`ApiClient`, ported from `azr::api_client` on httpx (design §4.1)."""

from __future__ import annotations

import dataclasses
import email.utils
import json as jsonlib
import logging
import random
import string
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Generator, Mapping
from typing import Any, ClassVar, TypeVar, cast, overload
from urllib.parse import quote

import httpx
from azure.core.credentials import AccessToken, TokenCredential
from rich.logging import RichHandler
from rich.markup import escape

from ._app_credential import app_credential
from .errors import ApiError, ResponseParseError

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

_T = TypeVar("_T")
_Client = TypeVar("_Client", bound="ApiClient")


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
        tries = cast(object, max_tries)  # checked at run time: callers may be untyped
        if not isinstance(tries, int) or tries < 1:
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

    def __enter__(self: _Client) -> _Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying `httpx.Client`."""
        self._http.close()

    @overload
    def fetch(
        self,
        path: str,
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,
        parse: None = None,
        **path_params: str,
    ) -> Any: ...

    @overload
    def fetch(
        self,
        path: str,
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,
        parse: Callable[[Any], _T],
        **path_params: str,
    ) -> _T: ...

    def fetch(
        self,
        path: str,
        method: str = "GET",
        *,
        query: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,
        parse: Callable[[Any], Any] | None = None,
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
        raises `ApiError`; a JSON or XML body that does not parse raises
        `ResponseParseError`.

        `json` is sent as JSON. A pydantic model (anything with `model_dump()`)
        is sent as `model_dump(mode="json", by_alias=True, exclude_unset=True)`,
        a dataclass instance field by field as `dataclasses.asdict()`, also when
        nested in lists, tuples, dict values or dataclass fields; logging shows
        the body as sent.

        `parse`, when given, replaces `response_handler` for this call: it is
        called with the parsed body of every 2xx response, `None` for an empty
        one, and `fetch()` returns what it returns (typed so).
        `TypeAdapter(list[Model]).validate_python` or `Model.model_validate`
        validate the body. An exception from `parse` raises
        `ResponseParseError`, chained to it.
        """
        url = _fill_path(path, path_params)
        method = method.upper()
        body = _to_json(json)
        response = self._send(method, url, params=query, json=body, headers=headers)
        if not response.is_success:
            raise ApiError(_error_message(response), request=response.request, response=response)
        result = _parse(response, content_type)
        if parse is not None:
            try:
                return parse(result)
            except Exception as exc:
                raise _parse_error(response, "was rejected by parse=", exc) from exc
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


def _to_json(value: Any) -> Any:
    """What `fetch(json=...)` sends: pydantic models and dataclass instances as dicts.

    Duck-typed, so pydantic is not imported: anything (not a class) with a
    callable `model_dump` is a pydantic v2 model (D51, D52). Models and
    dataclasses are converted wherever they are: at the top, in lists and
    tuples (sent as lists), in dict values and in dataclass fields. Dict keys
    are left alone; anything else is sent as given.
    """
    if isinstance(value, type):
        return value  # a class, not an instance: httpx refuses it as before
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", by_alias=True, exclude_unset=True)
    if dataclasses.is_dataclass(value):
        # As dataclasses.asdict(), field by field, so a model in a field is dumped too.
        return {f.name: _to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        items = cast("list[Any] | tuple[Any, ...]", value)
        return [_to_json(item) for item in items]
    if isinstance(value, dict):
        mapping = cast("dict[Any, Any]", value)
        return {key: _to_json(item) for key, item in mapping.items()}
    return value


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
    try:
        if media == "application/json":
            return response.json()
        if media == "application/xml":
            return ET.fromstring(response.content)
    except (ValueError, ET.ParseError) as exc:  # JSONDecodeError and UnicodeDecodeError too
        raise _parse_error(response, f"is not valid {media}", exc) from exc
    return response.text


def _parse_error(response: httpx.Response, what: str, exc: Exception) -> ResponseParseError:
    """`ResponseParseError` naming the method, URL and exception type, never the body (D54)."""
    request = response.request
    return ResponseParseError(
        f"{request.method} {request.url}: the response body {what} ({type(exc).__name__}).",
        request=request,
        response=response,
    )


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


class _Ellipsis:
    """Stands for the items `_abbreviate_json()` leaves out; prints as a bare `...`."""


_ELLIPSIS = _Ellipsis()


def _head_tail(items: list[Any], n: int) -> list[Any]:
    half = max(n // 2, 1)
    return [*items[:half], _ELLIPSIS, *items[-half:]]


def _abbreviate_json(obj: Any, max_items: int = 10, max_size: int = 12) -> str:
    """Pretty JSON text of `obj`, abbreviated as `azr`'s `format_json_body()`.

    An object or array with more than `max_items` items keeps the first and
    last `max_items // 2`, a nested array of scalars (an R atomic vector) with
    more than `max_size` the first and last `max_size // 2`, with a bare
    `...` between. The layout is jsonlite's `pretty = TRUE`: two-space
    indent, a nested array of scalars on one line. Differences from azr's
    text are in design §4.1.
    """

    def scalar(x: Any) -> str:
        return "..." if x is _ELLIPSIS else jsonlib.dumps(x, ensure_ascii=False)

    def is_atomic(x: list[Any]) -> bool:
        return bool(x) and not any(isinstance(i, (dict, list)) for i in x)

    def render(x: object, level: int, top: bool = False) -> str:
        pad, inner = "  " * level, "  " * (level + 1)
        if isinstance(x, dict):
            if not x:
                return "{}"
            items: list[Any] = list(cast("dict[str, Any]", x).items())
            if len(items) > max_items:
                items = _head_tail(items, max_items)
            lines = [
                f"{inner}..."
                if item is _ELLIPSIS
                else f"{inner}{scalar(item[0])}: {render(item[1], level + 1)}"
                for item in items
            ]
            return "{\n" + ",\n".join(lines) + f"\n{pad}}}"
        if isinstance(x, list):
            values: list[Any] = cast("list[Any]", x)
            if not values:
                return "[]"
            if not top and is_atomic(values):
                if len(values) > max_size:
                    values = _head_tail(values, max_size)
                return "[" + ", ".join(scalar(i) for i in values) + "]"
            if len(values) > max_items:
                values = _head_tail(values, max_items)
            lines = [
                f"{inner}..." if i is _ELLIPSIS else inner + render(i, level + 1) for i in values
            ]
            return "[\n" + ",\n".join(lines) + f"\n{pad}]"
        return scalar(x)

    return render(obj, 0, top=True)


def _json_body(content: bytes) -> str:
    """A JSON body abbreviated for the log; text that is not JSON as is."""
    try:
        obj = jsonlib.loads(content)
    except ValueError:
        return content.decode("utf-8", "replace")
    return _abbreviate_json(obj)


def _log_request(request: httpx.Request) -> None:
    request.extensions[_START] = _clock()
    logger.info(f"{_INFO} >>> %s %s", request.method, escape(str(request.url)))
    content = request.content
    if content and request.headers.get("content-type", "").startswith("application/json"):
        logger.info(f"{_INFO} >>> body:")
        logger.info("%s", escape(_json_body(content)))


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
            text = _json_body(body)
        else:
            text = response.text
        logger.info("%s", escape(text))
