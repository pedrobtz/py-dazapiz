"""Whether a person can answer a prompt in this session."""

from __future__ import annotations

import sys

__all__ = ["is_interactive"]


def is_interactive() -> bool:
    """True in a TTY or a notebook kernel, where a prompt can be answered.

    A batch job, a pipe or a scheduled notebook run without a kernel is not
    interactive, so a credential refuses there instead of waiting for input
    (design §4.3.3, §4.1.1, §4.2).
    """
    try:
        if sys.stdin.isatty():
            return True
    except (AttributeError, ValueError, OSError):  # None, closed or replaced stdin
        pass
    return _in_notebook_kernel()


def _in_notebook_kernel() -> bool:
    # Only look if IPython is already imported: importing it here would be slow
    # and would never find a kernel that is not running.
    ipython = sys.modules.get("IPython")
    get_ipython = getattr(ipython, "get_ipython", None)
    if get_ipython is None:
        return False
    try:
        shell = get_ipython()
    except Exception:
        return False
    return shell is not None and getattr(shell, "kernel", None) is not None
