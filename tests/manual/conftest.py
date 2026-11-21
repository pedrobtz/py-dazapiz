"""The live tests of the manual checklist (README.md here; design §8.2).

Every test under this directory is skipped unless `DAZURE_LIVE=1`. The
guard is a collection hook, not a marker each module must remember, so a
new `test_live_*.py` is skipped too. The modules import nothing beyond
`dazure`, `azure-identity` and the standard library at import time;
DuckDB and PySpark are imported inside the tests that need them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from live_helpers import jwt_claims

HERE = Path(__file__).parent
LIVE_REASON = "live Azure test of the manual checklist: set DAZURE_LIVE=1 (tests/manual/README.md)"


def live_enabled() -> bool:
    return os.environ.get("DAZURE_LIVE") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if live_enabled():
        return
    skip = pytest.mark.skip(reason=LIVE_REASON)
    for item in items:
        if HERE in item.path.parents:
            item.add_marker(skip)


@pytest.fixture
def env():
    """`env("NAME", ...)`: the variables' values; the test is skipped naming any unset one."""

    def get(*names: str) -> str | tuple[str, ...]:
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            pytest.skip(f"set {', '.join(missing)} (tests/manual/README.md)")
        values = tuple(os.environ[name] for name in names)
        return values[0] if len(values) == 1 else values

    return get


@pytest.fixture
def storage(env):
    """(account, container, path) of the test file, and its expected row count or None."""
    account, container, path = env(
        "DAZURE_TEST_STORAGE_ACCOUNT", "DAZURE_TEST_CONTAINER", "DAZURE_TEST_PATH"
    )
    rows = os.environ.get("DAZURE_TEST_ROWS")
    return account, container, path.lstrip("/"), int(rows) if rows else None


@pytest.fixture
def service_principal(env):
    """(tenant_id, client_id, client_secret) of the test service principal."""
    return env("DAZURE_TEST_TENANT_ID", "DAZURE_TEST_CLIENT_ID", "DAZURE_TEST_CLIENT_SECRET")


@pytest.fixture
def posix_only():
    if sys.platform == "win32":
        pytest.skip("refresh_token_from_az_cli() raises UnsupportedPlatformError on Windows")


@pytest.fixture
def claims():
    return jwt_claims
