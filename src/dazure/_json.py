"""Typed views of parsed JSON, for values `json.loads()` returns as `Any`."""

from __future__ import annotations

from typing import Any, cast

__all__ = ["json_object", "json_objects"]


def json_object(value: object) -> dict[str, Any] | None:
    """`value` if it is a JSON object (a dict; JSON keys are strings), else None."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def json_objects(value: object) -> list[dict[str, Any]]:
    """The JSON objects among the items of `value` if it is a list, else none."""
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [obj for item in items if (obj := json_object(item)) is not None]
