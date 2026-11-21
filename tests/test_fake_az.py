"""The fake `az` itself: a wrong fake would turn test_az.py's failures into passes."""

import os
import shutil
import subprocess
from pathlib import Path

FAKE_AZ_DIR = Path(__file__).parent / "fake_az"


def run(*args, **kwargs):
    az = shutil.which("az")
    return subprocess.run([az, *args], capture_output=True, text=True, timeout=30, **kwargs)


def test_is_first_on_path(fake_az):
    az = Path(shutil.which("az"))
    assert az.parent == fake_az.bin
    assert az.name.lower() == ("az.cmd" if os.name == "nt" else "az")


def test_records_argv_as_given(fake_az):
    fake_az.script("account show", {"stdout": "{}"})
    run("account", "show", "--output", "json", "--query", "user name")
    run("account", "show")
    assert fake_az.calls == [
        ["account", "show", "--output", "json", "--query", "user name"],
        ["account", "show"],
    ]


def test_plays_back_stdout_stderr_and_exit_code(fake_az):
    fake_az.script("logout", {"stdout": "out\n", "stderr": ["one", "two"], "exit": 3})
    result = run("logout", "--only-show-errors")
    assert (result.stdout, result.stderr.splitlines(), result.returncode) == (
        "out\n",
        ["one", "two"],
        3,
    )


def test_replies_in_turn_then_repeats_the_last(fake_az):
    fake_az.script("account show", [{"exit": 1}, {"exit": 0}])
    assert [run("account", "show").returncode for _ in range(3)] == [1, 0, 0]


def test_unscripted_command_fails(fake_az):
    fake_az.script("account show", {"stdout": "{}"})
    result = run("login", "--use-device-code")
    assert result.returncode == 99
    assert "'login'" in result.stderr


def test_streams_stderr_before_waiting(fake_az, tmp_path):
    release = tmp_path / "release"
    fake_az.script("login", {"stderr": ["prompt"], "wait_for": str(release), "stdout": "[]"})
    proc = subprocess.Popen(
        [shutil.which("az"), "login"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stderr.readline() == "prompt\n"  # seen while the fake is still waiting
    assert proc.poll() is None
    release.touch()
    out, _ = proc.communicate(timeout=30)
    assert (out, proc.returncode) == ("[]", 0)


def test_not_released_in_time_fails(fake_az, tmp_path):
    fake_az.script("login", {"wait_for": str(tmp_path / "never"), "wait_timeout": 0.2})
    result = run("login")
    assert result.returncode == 97


def test_stubs_launch_fake_az_py():
    # The other OS's stub is not run on this leg, so check its text here.
    assert (
        '"$DAZURE_FAKE_AZ_PYTHON" "$(dirname "$0")/fake_az.py" "$@"'
        in (FAKE_AZ_DIR / "az").read_text()
    )
    assert '"%DAZURE_FAKE_AZ_PYTHON%" "%~dp0fake_az.py" %*' in (FAKE_AZ_DIR / "az.cmd").read_text()
