"""Release all RUNNING Browserbase sessions (keep_alive sessions don't end on
CDP disconnect — they hold concurrency slots until released or idle-timeout).

    set -a && source .env && set +a && uv run python -m backend.release_sessions
"""

from __future__ import annotations

import os

from browserbase import Browserbase


def main() -> None:
    bb = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
    pid = os.environ["BROWSERBASE_PROJECT_ID"]
    running = list(bb.sessions.list(status="RUNNING"))
    print(f"{len(running)} RUNNING session(s)")
    for s in running:
        try:
            bb.sessions.update(s.id, project_id=pid, status="REQUEST_RELEASE")
            print("released", s.id)
        except Exception as exc:
            print("FAILED to release", s.id, "->", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
