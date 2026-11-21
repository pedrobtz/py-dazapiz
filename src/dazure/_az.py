"""The `az` CLI helpers: account show, login, logout (design §4.2).

Plain `subprocess` wrappers around the `az` that `shutil.which("az")` finds,
ported from `azr`'s `az_cli_*()` functions. Getting tokens from the CLI is not
wrapped here: that is `azure.identity.AzureCliCredential`.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from typing import Any

from . import _session
from ._spark_conf import _check_tenant
from .errors import (
    AzCliError,
    AzCliNonInteractiveError,
    AzCliNotFoundError,
    AzCliNotLoggedInError,
    AzCliTimeoutError,
)

__all__ = ["az_account_show", "az_is_login", "az_login", "az_logout"]

_TIMEOUT = 10
_LOGIN_URL = "https://microsoft.com/devicelogin"
# MSAL's device-flow message, which `az login --use-device-code` prints to stderr:
# "To sign in, use a web browser to open the page <url> and enter the code <code>
# to authenticate." The code pattern is azr's.
_CODE_RE = re.compile(r"enter the code ([A-Z0-9]+) to authenticate")
_URL_RE = re.compile(r"https?://\S+")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Tried in turn; the first found on PATH that exits 0 has the code. Patched by tests.
_CLIPBOARD_TOOLS: tuple[tuple[str, ...], ...] = (
    ("pbcopy",),  # macOS
    ("clip",),  # Windows
    ("wl-copy",),  # Wayland
    ("xclip", "-selection", "clipboard"),
    ("xsel", "--clipboard", "--input"),
)


def az_account_show(timeout: float | None = _TIMEOUT) -> dict[str, Any]:
    """The Azure CLI's current account, from `az account show --output json`.

    Raises `AzCliNotLoggedInError` when the CLI is not logged in,
    `AzCliNotFoundError` when there is no `az` on PATH, `AzCliTimeoutError`
    when `az` does not finish within `timeout` seconds (`None` waits), and
    `AzCliError` on any other failure.
    """
    args = ["account", "show", "--output", "json"]
    code, out, err = _run(args, timeout)
    if code != 0:
        raise _failure(args, code, err)
    try:
        account = json.loads(out)
    except ValueError:
        raise AzCliError("`az account show` did not return JSON.") from None
    if not isinstance(account, dict):
        raise AzCliError("`az account show` did not return a JSON object.")
    return account


def az_is_login(timeout: float | None = _TIMEOUT) -> bool:
    """Whether the Azure CLI is logged in, by `az account show`.

    False on any `AzCliError`, including no `az` on PATH and a timeout, as
    `azr::az_cli_is_login()` returns `FALSE` on any error.
    """
    try:
        az_account_show(timeout)
    except AzCliError:
        return False
    return True


def az_login(
    tenant_id: str | None = None,
    *,
    force: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Log the Azure CLI in with a device code, unless it already is.

    Unless `force`, returns the current account without prompting when the CLI
    is logged in (into `tenant_id`, if given). Otherwise runs
    `az login --use-device-code [--tenant <tenant_id>] --output json`, prints
    the device code and URL as soon as `az` streams them on stderr, copies the
    code to the clipboard when a clipboard tool is found, waits for `az` to
    finish and returns the account it made the default.

    Raises `AzCliNonInteractiveError` when nobody can answer the prompt (no
    TTY and no notebook kernel), `AzCliTimeoutError` when `timeout` seconds
    pass first (`None`, the default, waits), and `AzCliError` when `az login`
    fails. Prints the device code and the account name, nothing else from
    the login (design §6).
    """
    if tenant_id is not None:
        if not isinstance(tenant_id, str):
            raise TypeError(f"tenant_id must be a string, not {type(tenant_id).__name__}")
        _check_tenant(tenant_id)

    if not force:
        account = _current_account(tenant_id)
        if account is not None:
            print(
                f"Already logged in to the Azure CLI as {_user_name(account)}; "
                "use force=True to log in again.",
                flush=True,
            )
            return account

    if not _session.is_interactive():
        raise AzCliNonInteractiveError(
            "az_login() needs an interactive session (a TTY or a notebook kernel) "
            "to show the device code; run `az login` where you can answer it."
        )

    args = ["login", "--use-device-code"]
    if tenant_id is not None:
        args += ["--tenant", tenant_id]
    args += ["--output", "json"]
    code, out, err = _stream_login(args, timeout)
    if code != 0:
        raise _failure(args, code, err)

    account = _default_account(out)
    if account is None:
        account = az_account_show()
    print(f"Logged in to the Azure CLI as {_user_name(account)}.", flush=True)
    return account


def az_logout(timeout: float | None = _TIMEOUT) -> None:
    """Log the Azure CLI out, by `az logout`.

    Raises `AzCliNotLoggedInError` when no account is logged in, and the other
    errors as `az_account_show()`.
    """
    args = ["logout"]
    code, _, err = _run(args, timeout)
    if code != 0:
        raise _failure(args, code, err)
    print("Logged out of the Azure CLI.", flush=True)


# Running az ---------------------------------------------------------------------


def _az() -> str:
    path = shutil.which("az")
    if path is None:
        raise AzCliNotFoundError(
            "The Azure CLI (`az`) is not on PATH. To install it, see "
            "https://learn.microsoft.com/cli/azure/install-azure-cli"
        )
    return path


def _argv(args: list[str]) -> list[str]:
    return [_az(), *args, "--only-show-errors"]


# `az` is a script that starts Python (`az.cmd` runs it under cmd.exe on Windows), so
# a timeout kills the whole tree: killing only the first process would leave the
# child holding the pipes open until it finished.
def _popen_kwargs() -> dict[str, Any]:
    return {} if os.name == "nt" else {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        taskkill = os.path.join(
            os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe"
        )
        subprocess.run(
            [taskkill, "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    proc.kill()


def _timeout_error(args: list[str], timeout: float | None) -> AzCliTimeoutError:
    return AzCliTimeoutError(f"`az {' '.join(args)}` did not finish within {timeout} s.")


def _run(args: list[str], timeout: float | None) -> tuple[int, str, str]:
    argv = _argv(args)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_popen_kwargs(),
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        raise _timeout_error(args, timeout) from None
    except BaseException:
        _kill_tree(proc)
        raise
    return proc.returncode, out, err


def _stream_login(args: list[str], timeout: float | None) -> tuple[int, str, str]:
    # stdout (the account list) goes to a file, so a long list cannot fill a pipe
    # nobody reads while stderr is read line by line, as azr does.
    argv = _argv(args)
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        timed_out = threading.Event()

        def expire() -> None:
            if proc.poll() is None:
                timed_out.set()
                _kill_tree(proc)

        timer = threading.Timer(timeout, expire) if timeout is not None else None
        err: list[str] = []
        try:
            if timer is not None:
                timer.daemon = True
                timer.start()
            shown = False
            assert proc.stderr is not None
            for line in proc.stderr:
                err.append(line)
                if not shown:
                    shown = _show_device_code(line)
            proc.wait()
        except BaseException:
            _kill_tree(proc)
            raise
        finally:
            if timer is not None:
                timer.cancel()
            if proc.stderr is not None:
                proc.stderr.close()
        if timed_out.is_set():
            raise _timeout_error(args, timeout)
        out.seek(0)
        return proc.returncode, out.read(), "".join(err)


def _failure(args: list[str], code: int, err: str) -> AzCliError:
    message = _ANSI_RE.sub("", err).strip() or f"no message (exit code {code})"
    if "az login" in message or "no active accounts" in message.lower():
        return AzCliNotLoggedInError(
            f"The Azure CLI is not logged in: {message} Log in with dazure.az_login()."
        )
    return AzCliError(f"`az {' '.join(args)}` failed with exit code {code}: {message}")


# Login --------------------------------------------------------------------------


def _current_account(tenant_id: str | None) -> dict[str, Any] | None:
    # The logged-in account, or None when the CLI is not logged in or is logged in
    # to a tenant other than the one asked for (azr's az_cli_current_account()).
    try:
        account = az_account_show()
    except AzCliNotLoggedInError:
        return None
    if tenant_id is not None and str(account.get("tenantId", "")).lower() != tenant_id.lower():
        return None
    return account


def _default_account(out: str) -> dict[str, Any] | None:
    # `az login --output json` lists the accounts it found; the default one is what
    # `az account show` shows next.
    try:
        accounts = json.loads(out)
    except ValueError:
        return None
    if not isinstance(accounts, list):
        return None
    accounts = [a for a in accounts if isinstance(a, dict)]
    for a in accounts:
        if a.get("isDefault") is True:
            return a
    return accounts[0] if accounts else None


def _user_name(account: dict[str, Any]) -> str:
    user = account.get("user")
    name = user.get("name") if isinstance(user, dict) else None
    return str(name) if name else "an unnamed account"


def _show_device_code(line: str) -> bool:
    line = _ANSI_RE.sub("", line)
    match = _CODE_RE.search(line)
    if match is None:
        return False
    code = match.group(1)
    url = _URL_RE.search(line)
    print(
        f"To sign in, open {url.group(0) if url else _LOGIN_URL} and enter the code {code}.",
        flush=True,
    )
    if _copy_to_clipboard(code):
        print("The code is copied to the clipboard.", flush=True)
    return True


def _copy_to_clipboard(text: str) -> bool:
    """Put `text` on the clipboard with the first tool that works; never raises.

    `azr` copies the code with `clipr`, which runs the same tools.
    """
    for tool in _CLIPBOARD_TOOLS:
        path = shutil.which(tool[0])
        if path is None:
            continue
        try:
            result = subprocess.run(
                [path, *tool[1:]],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return True
    return False
