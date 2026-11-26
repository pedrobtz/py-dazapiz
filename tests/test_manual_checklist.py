"""The live tests of tests/manual/ are collected, and skipped without DAZAPIZ_LIVE=1."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MANUAL = ROOT / "tests" / "manual"


# Modules that need no Azure, skipped unless DAZAPIZ_LIVE_HTTP=1 (item 8).
LIVE_HTTP = {"test_live_petstore"}


def _env(live: str | None, live_http: str | None = None) -> dict[str, str]:
    drop = {"DAZAPIZ_LIVE", "DAZAPIZ_LIVE_HTTP"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    if live is not None:
        env["DAZAPIZ_LIVE"] = live
    if live_http is not None:
        env["DAZAPIZ_LIVE_HTTP"] = live_http
    return env


def _run_manual(tmp_path, env, *args) -> dict[str, list[ET.Element]]:
    report = tmp_path / "junit.xml"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(MANUAL),
            "-p",
            "no:cacheprovider",
            "-q",
            "--junitxml",
            str(report),
            *args,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    by_file: dict[str, list[ET.Element]] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        by_file.setdefault(case.get("classname").split(".")[-1], []).append(case)
    return by_file


def _skip_message(name: str, case: ET.Element) -> str:
    skipped = case.find("skipped")
    assert skipped is not None, f"{name}::{case.get('name')} was not skipped"
    return skipped.get("message", "")


@pytest.mark.parametrize(
    ("live", "live_http"),
    [(None, None), ("0", "0"), ("true", "true"), (None, "yes")],
    ids=["unset", "0", "true", "yes"],
)
def test_live_tests_are_collected_and_skipped(tmp_path, live, live_http):
    by_file = _run_manual(tmp_path, _env(live, live_http))
    live_files = {p.stem for p in MANUAL.glob("test_live_*.py")}
    assert len(live_files) >= 5
    assert live_files >= LIVE_HTTP
    assert set(by_file) == live_files

    for name, file_cases in by_file.items():
        reason = "DAZAPIZ_LIVE_HTTP=1" if name in LIVE_HTTP else "DAZAPIZ_LIVE=1"
        for case in file_cases:
            message = _skip_message(name, case)
            assert reason in message
            assert ("no Azure" in message) == (name in LIVE_HTTP)


def test_live_http_does_not_turn_on_the_azure_tests(tmp_path):
    # DAZAPIZ_LIVE_HTTP=1 alone leaves every Azure item skipped (the Petstore
    # module is deselected so this test makes no request).
    by_file = _run_manual(tmp_path, _env(None, "1"), "-k", "not petstore")
    assert by_file
    assert not set(by_file) & LIVE_HTTP
    for name, file_cases in by_file.items():
        for case in file_cases:
            assert "DAZAPIZ_LIVE=1" in _skip_message(name, case)


def test_interactive_helper_runs_nothing_on_import():
    run = subprocess.run(
        [sys.executable, "-c", "import interactive, live_helpers"],
        cwd=MANUAL,
        env=_env(None),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == ""
    assert run.stderr == ""
