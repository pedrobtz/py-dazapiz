"""A fake `az` for the tests: records its arguments and plays back a script.

Launched by the `az` shell stub on POSIX and `az.cmd` on Windows, which the
`fake_az` fixture (tests/conftest.py) puts first on PATH. It reads two
environment variables:

- `DAZURE_FAKE_AZ_LOG`: a JSON-lines file; each run appends `{"argv": [...]}`
  with its arguments, the program name left out.
- `DAZURE_FAKE_AZ_SCRIPT`: a JSON file mapping a command (the leading
  arguments that are not options, such as `"account show"`) to a reply, or
  to a list of replies used in turn, the last one repeating.

A reply has optional keys, played in this order:

- `stderr`: lines written to stderr, each flushed at once, as `az login`
  streams its device-code prompt;
- `wait_for`: a path; the fake waits until it exists, up to
  `wait_timeout` seconds (default 10), else exits 97. A test creates the
  file only once it has seen the stderr lines, so a caller that reads them
  only after exit makes the fake fail;
- `sleep`: seconds to sleep;
- `stdout`: text written to stdout;
- `exit`: the exit code (default 0).

A command with no reply exits 99, so a test never passes on a call it did not
script.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def command_of(argv: list[str]) -> str:
    words = []
    for arg in argv:
        if arg.startswith("-"):
            break
        words.append(arg)
    return " ".join(words)


def main() -> int:
    argv = sys.argv[1:]
    log = Path(os.environ["DAZURE_FAKE_AZ_LOG"])
    previous = []
    if log.exists():
        previous = [json.loads(line)["argv"] for line in log.read_text("utf-8").splitlines()]
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv}) + "\n")

    command = command_of(argv)
    script = json.loads(Path(os.environ["DAZURE_FAKE_AZ_SCRIPT"]).read_text("utf-8"))
    replies = script.get(command)
    if replies is None:
        sys.stderr.write(f"fake az: no reply scripted for {command!r}\n")
        return 99
    if isinstance(replies, dict):
        replies = [replies]
    n = sum(command_of(a) == command for a in previous)
    reply = replies[min(n, len(replies) - 1)]

    for line in reply.get("stderr", []):
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    if "wait_for" in reply:
        deadline = time.monotonic() + reply.get("wait_timeout", 10)
        while not Path(reply["wait_for"]).exists():
            if time.monotonic() > deadline:
                sys.stderr.write("fake az: never released\n")
                return 97
            time.sleep(0.05)
    if "sleep" in reply:
        time.sleep(reply["sleep"])
    sys.stdout.write(reply.get("stdout", ""))
    sys.stdout.flush()
    return reply.get("exit", 0)


if __name__ == "__main__":
    sys.exit(main())
