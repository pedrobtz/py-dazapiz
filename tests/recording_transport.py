"""An `httpx.MockTransport` that records every whole request and plays a script.

`RecordingTransport(script)` serves the script's entries in turn, one per
request: an `httpx.Response`, or an exception (an instance or a class) to
raise (httpx attaches the request to an `httpx.RequestError`).
The last entry is not repeated: a request past the end of the script fails
the test with `AssertionError`. `requests` is the list of `Recorded`
requests (method, URL, headers, body), whole, in the order they were sent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import httpx

__all__ = ["Recorded", "RecordingTransport", "json_response"]


@dataclass(frozen=True)
class Recorded:
    """One request as it reached the transport."""

    method: str
    url: httpx.URL
    headers: httpx.Headers
    body: bytes


Entry = httpx.Response | BaseException | type[BaseException]


class RecordingTransport(httpx.MockTransport):
    def __init__(self, script: Iterable[Entry] = ()) -> None:
        super().__init__(self._handle)
        self.script: list[Entry] = list(script)
        self.requests: list[Recorded] = []

    def add(self, *entries: Entry) -> None:
        self.script.extend(entries)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            Recorded(request.method, request.url, httpx.Headers(request.headers), request.read())
        )
        if not self.script:
            raise AssertionError(f"unscripted request: {request.method} {request.url}")
        entry = self.script.pop(0)
        if isinstance(entry, type):
            entry = entry("scripted error")
        if isinstance(entry, BaseException):
            raise entry
        return entry


def json_response(status: int, body: object, **kwargs) -> httpx.Response:
    """A response whose body is `body` as JSON, with `application/json; charset=utf-8`."""
    import json

    return httpx.Response(
        status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json; charset=utf-8", **kwargs.pop("headers", {})},
        **kwargs,
    )
