"""The az CLI helpers against the fake `az` of tests/fake_az/ (design §4.2)."""

import json
import subprocess
import sys
import time
from typing import ClassVar

import pytest

import dazapiz._az
import dazapiz._session
from dazapiz import az_account_show, az_is_login, az_login, az_logout
from dazapiz.errors import (
    AzCliError,
    AzCliNonInteractiveError,
    AzCliNotFoundError,
    AzCliNotLoggedInError,
    AzCliTimeoutError,
    DazapizError,
)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
CODE = "F7GH2K9QX"
URL = "https://microsoft.com/devicelogin"
# What MSAL puts in the flow's message and `az login` prints to stderr.
PROMPT = f"To sign in, use a web browser to open the page {URL} and enter the code {CODE} to authenticate."
NOT_LOGGED_IN = {"stderr": ["ERROR: Please run 'az login' to setup account."], "exit": 1}


def account(user="alice@contoso.com", tenant=TENANT, default=True, sub="Sub one"):
    # The shape of `az account show --output json`, and of each entry `az login` lists.
    return {
        "environmentName": "AzureCloud",
        "homeTenantId": tenant,
        "id": "33333333-3333-3333-3333-333333333333",
        "isDefault": default,
        "managedByTenants": [],
        "name": sub,
        "state": "Enabled",
        "tenantId": tenant,
        "user": {"name": user, "type": "user"},
    }


def shown(acct):
    return {"stdout": json.dumps(acct)}


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: True)


def login_reply(accounts, **extra):
    return {"stderr": [PROMPT], "stdout": json.dumps(accounts), **extra}


# Arguments sent to az, as the fake recorded them ---------------------------------


def test_account_show_args(fake_az):
    fake_az.script("account show", shown(account()))
    assert az_account_show() == account()
    assert az_is_login() is True
    expected = ["account", "show", "--output", "json", "--only-show-errors"]
    assert fake_az.calls == [expected, expected]


def test_logout_args(fake_az, capsys):
    fake_az.script("logout", {})
    assert az_logout() is None
    assert fake_az.calls == [["logout", "--only-show-errors"]]


def test_login_args(fake_az, interactive):
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", login_reply([account()]))
    az_login()
    az_login(TENANT, force=True)
    assert fake_az.calls == [
        ["account", "show", "--output", "json", "--only-show-errors"],
        ["login", "--use-device-code", "--output", "json", "--only-show-errors"],
        [
            "login",
            "--use-device-code",
            "--tenant",
            TENANT,
            "--output",
            "json",
            "--only-show-errors",
        ],
    ]


# az_login() ---------------------------------------------------------------------


def test_login_already_logged_in_returns_without_prompting(fake_az, capsys):
    # No TTY patch: a reused login needs no prompt, as in azr.
    fake_az.script("account show", shown(account()))
    assert az_login() == account()
    assert [c[0] for c in fake_az.calls] == ["account"]
    assert "Already logged in to the Azure CLI as alice@contoso.com" in capsys.readouterr().out


def test_login_force_logs_in_again(fake_az, interactive):
    fake_az.script("account show", shown(account()))
    fake_az.script("login", login_reply([account("bob@contoso.com")]))
    assert az_login(force=True)["user"]["name"] == "bob@contoso.com"
    assert [c[0] for c in fake_az.calls] == ["login"]


def test_login_tenant_match(fake_az, interactive):
    fake_az.script("account show", shown(account(tenant=TENANT)))
    fake_az.script("login", login_reply([account(tenant=OTHER_TENANT)]))
    # The same tenant, in other case: reused.
    assert az_login(TENANT.upper())["tenantId"] == TENANT
    assert [c[0] for c in fake_az.calls] == ["account"]
    # Another tenant: a new login into it.
    assert az_login(OTHER_TENANT)["tenantId"] == OTHER_TENANT
    assert [c[0] for c in fake_az.calls] == ["account", "account", "login"]
    assert fake_az.calls[-1][3] == OTHER_TENANT


@pytest.mark.parametrize("prompt", [PROMPT, f"\x1b[93m{PROMPT}\x1b[0m"], ids=["plain", "styled"])
def test_login_streams_the_device_code(fake_az, interactive, monkeypatch, tmp_path, capsys, prompt):
    # The fake waits, after its prompt, until the code reaches the clipboard: a login
    # that read stderr only after exit would make the fake fail with 97.
    release = tmp_path / "release"
    copied = []

    def copy(text):
        copied.append(text)
        release.touch()
        return True

    monkeypatch.setattr(dazapiz._az, "_copy_to_clipboard", copy)
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script(
        "login", login_reply([account()], stderr=[prompt], wait_for=str(release), wait_timeout=20)
    )
    assert az_login() == account()
    assert copied == [CODE]
    out = capsys.readouterr().out
    assert f"open {URL} and enter the code {CODE}" in out
    assert "copied to the clipboard" in out
    assert "Logged in to the Azure CLI as alice@contoso.com" in out


def test_login_without_clipboard_still_prints_the_code(fake_az, interactive, monkeypatch, capsys):
    monkeypatch.setattr(dazapiz._az, "_copy_to_clipboard", lambda text: False)
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", login_reply([account()]))
    az_login()
    out = capsys.readouterr().out
    assert CODE in out
    assert "clipboard" not in out


def test_login_prints_only_the_device_code_line(fake_az, interactive, capsys):
    # az writes other lines to stderr before its prompt; none of them is shown.
    warning = "WARNING: A web browser has not been opened. Use the code below."
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", login_reply([account()], stderr=[warning, PROMPT, "WARNING: later"]))
    az_login()
    out = capsys.readouterr().out
    assert f"enter the code {CODE}" in out
    assert "WARNING" not in out
    assert fake_az.copied == [CODE]


def test_login_no_tty_raises(fake_az, monkeypatch):
    monkeypatch.setattr(dazapiz._session, "is_interactive", lambda: False)
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", login_reply([account()]))
    with pytest.raises(AzCliNonInteractiveError):
        az_login()
    assert [c[0] for c in fake_az.calls] == ["account"]


def test_login_returns_the_default_account(fake_az, interactive):
    fake_az.script("account show", NOT_LOGGED_IN)
    accounts = [account(sub="first", default=False), account(sub="second", default=True)]
    fake_az.script("login", login_reply(accounts))
    assert az_login()["name"] == "second"


@pytest.mark.parametrize(
    "stdout", ["[]", "not json", "{}", "42"], ids=["empty", "not-json", "object", "number"]
)
def test_login_without_listed_accounts_reads_account_show(fake_az, interactive, stdout):
    fake_az.script("account show", [NOT_LOGGED_IN, shown(account())])
    fake_az.script("login", {"stderr": [PROMPT], "stdout": stdout})
    assert az_login() == account()
    assert [c[0] for c in fake_az.calls] == ["account", "login", "account"]


def test_login_failure_raises_with_az_message(fake_az, interactive):
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", {"stderr": [PROMPT, "ERROR: AADSTS70016: expired"], "exit": 1})
    with pytest.raises(AzCliError, match="AADSTS70016") as err:
        az_login()
    assert not isinstance(err.value, AzCliNotLoggedInError)


@pytest.mark.parametrize("tenant", ["", "a b", "x/../y", 42])
def test_login_refuses_a_bad_tenant(fake_az, tenant):
    with pytest.raises((ValueError, TypeError)):
        az_login(tenant)
    assert fake_az.calls == []


# Errors -------------------------------------------------------------------------


def test_errors_derive_from_dazapiz_error():
    for cls in (AzCliNotFoundError, AzCliNotLoggedInError, AzCliNonInteractiveError):
        assert issubclass(cls, AzCliError)
    assert issubclass(AzCliTimeoutError, AzCliError)
    assert issubclass(AzCliTimeoutError, TimeoutError)
    assert issubclass(AzCliError, DazapizError)


@pytest.fixture
def no_az(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.chdir(empty)  # Windows also looks in the current directory


def test_no_az_on_path(no_az, interactive):
    for call in (az_account_show, az_logout, lambda: az_login(force=True)):
        with pytest.raises(AzCliNotFoundError, match="install"):
            call()
    assert az_is_login() is False


def test_not_logged_in(fake_az):
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("logout", {"stderr": ["ERROR: There are no active accounts."], "exit": 1})
    with pytest.raises(AzCliNotLoggedInError, match="az login"):
        az_account_show()
    assert az_is_login() is False
    with pytest.raises(AzCliNotLoggedInError, match="no active accounts"):
        az_logout()


def test_other_failure_is_not_not_logged_in(fake_az):
    fake_az.script("account show", {"stderr": ["ERROR: something broke"], "exit": 2})
    with pytest.raises(AzCliError, match="something broke") as err:
        az_account_show()
    assert not isinstance(err.value, AzCliNotLoggedInError)
    fake_az.script("account show", {"stdout": "not json"})
    with pytest.raises(AzCliError, match="JSON"):
        az_account_show()
    fake_az.script("account show", {"stdout": "[]"})
    with pytest.raises(AzCliError, match="JSON object"):
        az_account_show()


def test_timeout(fake_az, interactive):
    fake_az.script("account show", {"sleep": 30, **shown(account())})
    fake_az.script("logout", {"sleep": 30})
    fake_az.script("login", {"stderr": [PROMPT], "sleep": 30, "stdout": "[]"})
    for call in (
        lambda: az_account_show(timeout=0.5),
        lambda: az_logout(timeout=0.5),
        lambda: az_login(force=True, timeout=0.5),
    ):
        start = time.monotonic()
        with pytest.raises(AzCliTimeoutError, match=r"0\.5"):
            call()
        # The process tree is killed, not waited for (cmd.exe's child on Windows).
        assert time.monotonic() - start < 15
    assert az_is_login(timeout=0.5) is False


class RecordingPopen(subprocess.Popen):
    """subprocess.Popen, keeping each process it starts."""

    started: ClassVar[list[subprocess.Popen]] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        RecordingPopen.started.append(self)


@pytest.fixture
def popen(monkeypatch):
    RecordingPopen.started = []
    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
    return RecordingPopen


def assert_killed(proc):
    # The fake sleeps 30 s: a process still running would time this wait out.
    try:
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()


def test_interrupt_kills_az(fake_az, popen, monkeypatch):
    # Ctrl-C while waiting for az: az is killed, not left running, and the
    # interrupt goes on.
    fake_az.script("account show", {"sleep": 30, **shown(account())})

    real_communicate = subprocess.Popen.communicate

    def interrupted(self, input=None, timeout=None):
        # Only az's wait: on Windows the kill runs taskkill.exe, also a Popen.
        if "account" in self.args:
            raise KeyboardInterrupt
        return real_communicate(self, input, timeout)

    monkeypatch.setattr(RecordingPopen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        az_account_show(timeout=None)
    # On Windows the kill itself starts taskkill.exe, also recorded.
    procs = [p for p in popen.started if "account" in p.args]
    assert len(procs) == 1
    assert_killed(procs[0])


def test_interrupt_kills_az_login(fake_az, interactive, popen, monkeypatch):
    fake_az.script("account show", NOT_LOGGED_IN)
    fake_az.script("login", {"stderr": [PROMPT], "sleep": 30, "stdout": "[]"})

    def interrupted(line):
        raise KeyboardInterrupt

    monkeypatch.setattr(dazapiz._az, "_show_device_code", interrupted)
    with pytest.raises(KeyboardInterrupt):
        az_login()
    login = [p for p in popen.started if "login" in p.args]
    assert len(login) == 1
    assert_killed(login[0])


def test_default_timeouts():
    import inspect

    for fn in (az_account_show, az_is_login, az_logout):
        assert inspect.signature(fn).parameters["timeout"].default == 10
    assert inspect.signature(az_login).parameters["timeout"].default is None


# The clipboard ------------------------------------------------------------------


def test_clipboard_uses_the_first_tool_that_works(monkeypatch, tmp_path):
    target = tmp_path / "clip.txt"
    writer = f"import sys; open({str(target)!r}, 'w').write(sys.stdin.read())"
    monkeypatch.setattr(
        dazapiz._az,
        "_CLIPBOARD_TOOLS",
        (
            ("no-such-clipboard-tool",),
            (sys.executable, "-c", "raise SystemExit(1)"),
            (sys.executable, "-c", writer),
        ),
    )
    assert dazapiz._az._copy_to_clipboard(CODE) is True
    assert target.read_text() == CODE


def test_clipboard_fails_silently(monkeypatch, capsys):
    monkeypatch.setattr(
        dazapiz._az,
        "_CLIPBOARD_TOOLS",
        (("no-such-clipboard-tool",), (sys.executable, "-c", "raise SystemExit(1)")),
    )
    assert dazapiz._az._copy_to_clipboard(CODE) is False
    assert capsys.readouterr() == ("", "")


def test_clipboard_skips_a_tool_that_errors(monkeypatch, tmp_path):
    # A tool that hangs (timeout) or cannot start is skipped for the next one.
    target = tmp_path / "clip.txt"
    writer = f"import sys; open({str(target)!r}, 'w').write(sys.stdin.read())"
    hangs = (sys.executable, "-c", "pass  # hangs")
    monkeypatch.setattr(dazapiz._az, "_CLIPBOARD_TOOLS", (hangs, (sys.executable, "-c", writer)))
    real_run = subprocess.run

    def run(argv, **kwargs):
        if argv[-1] == hangs[-1]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    assert dazapiz._az._copy_to_clipboard(CODE) is True
    assert target.read_text() == CODE
