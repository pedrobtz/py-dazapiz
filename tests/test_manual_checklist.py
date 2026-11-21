"""The live tests of tests/manual/ are collected, and skipped without DAZURE_LIVE=1."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MANUAL = ROOT / "tests" / "manual"


def _env(live: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "DAZURE_LIVE"}
    if live is not None:
        env["DAZURE_LIVE"] = live
    return env


@pytest.mark.parametrize("live", [None, "0", "true"], ids=["unset", "0", "true"])
def test_live_tests_are_collected_and_skipped(tmp_path, live):
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
        ],
        cwd=ROOT,
        env=_env(live),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stdout + run.stderr

    cases = ET.parse(report).getroot().iter("testcase")
    by_file: dict[str, list[ET.Element]] = {}
    for case in cases:
        by_file.setdefault(case.get("classname").split(".")[-1], []).append(case)
    live_files = {p.stem for p in MANUAL.glob("test_live_*.py")}
    assert len(live_files) >= 4
    assert set(by_file) == live_files

    for name, file_cases in by_file.items():
        for case in file_cases:
            skipped = case.find("skipped")
            assert skipped is not None, f"{name}::{case.get('name')} was not skipped"
            assert "DAZURE_LIVE=1" in skipped.get("message", "")


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
