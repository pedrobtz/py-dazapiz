"""Constants and helpers shared by the live tests and `interactive.py`."""

from __future__ import annotations

import base64
import json

ARM = "https://management.azure.com"
ARM_SCOPE = f"{ARM}/.default"


def jwt_claims(token: str) -> dict:
    """The payload of a JWT access token, decoded without verification; never printed."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
