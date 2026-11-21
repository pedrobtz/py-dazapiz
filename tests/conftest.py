"""Shared fixtures."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import dazure._az

FAKE_AZ_DIR = Path(__file__).parent / "fake_az"


class FakeAz:
    """The fake `az` of tests/fake_az/, first on PATH, and what it recorded.

    `script(command, reply)` sets the reply to one command (see fake_az.py
    for the keys); `calls` is the list of argument lists it was run with;
    `copied` is what `az_login()` sent to the clipboard, which the fixture
    replaces so no test touches the real one.
    """

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bin = root / "bin"
        self.bin.mkdir(parents=True)
        self.log = root / "calls.jsonl"
        self.script_file = root / "script.json"
        self._script: dict = {}
        self._write()
        self.copied: list[str] = []
        stub = "az.cmd" if os.name == "nt" else "az"
        shutil.copy(FAKE_AZ_DIR / "fake_az.py", self.bin / "fake_az.py")
        shutil.copy(FAKE_AZ_DIR / stub, self.bin / stub)
        (self.bin / stub).chmod(0o755)
        monkeypatch.setenv("PATH", str(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        monkeypatch.setenv("DAZURE_FAKE_AZ_PYTHON", sys.executable)
        monkeypatch.setenv("DAZURE_FAKE_AZ_LOG", str(self.log))
        monkeypatch.setenv("DAZURE_FAKE_AZ_SCRIPT", str(self.script_file))
        monkeypatch.setattr(dazure._az, "_copy_to_clipboard", self._copy)

    def script(self, command: str, reply: dict | list[dict]) -> None:
        self._script[command] = reply
        self._write()

    @property
    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        lines = self.log.read_text("utf-8").splitlines()
        return [json.loads(line)["argv"] for line in lines]

    def _write(self) -> None:
        self.script_file.write_text(json.dumps(self._script), "utf-8")

    def _copy(self, text: str) -> bool:
        self.copied.append(text)
        return True


@pytest.fixture
def fake_az(tmp_path, monkeypatch) -> FakeAz:
    """Put the fake `az` first on PATH; see `FakeAz`."""
    return FakeAz(tmp_path / "fake_az", monkeypatch)


@pytest.fixture(scope="session")
def azure_extension():
    """DuckDB's azure extension, installed once; CI caches its directory.

    In CI a failed install fails the tests that need it. Elsewhere, offline,
    they are skipped with the reason.
    """
    duckdb = pytest.importorskip("duckdb", reason="needs the duckdb extra")
    conn = duckdb.connect()
    try:
        conn.execute("INSTALL azure")
    except duckdb.Error as err:
        if os.environ.get("CI"):
            pytest.fail(f"cannot install DuckDB's azure extension in CI: {err}")
        pytest.skip(f"DuckDB's azure extension is not installed and cannot be: {err}")
    finally:
        conn.close()
