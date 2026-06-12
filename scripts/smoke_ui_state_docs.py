#!/usr/bin/env python3
"""Check public docs/front-end do not reintroduce legacy /state guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_PATHS = [
    "README.md",
    "docs/AGENT_API.md",
    "backend/static/js/app.js",
    "backend/static/js/core.js",
    "backend/static/index.html",
]
ALLOWED_STATE_MENTIONS = {
    "docs/AGENT_API.md": ["legacy `/state`"],
}


def main() -> int:
    for rel in CHECK_PATHS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        allowed = ALLOWED_STATE_MENTIONS.get(rel, [])
        for line_no, line in enumerate(text.splitlines(), 1):
            if "/state" not in line:
                continue
            if any(fragment in line for fragment in allowed):
                continue
            raise SystemExit(f"unexpected /state mention in {rel}:{line_no}: {line}")
    print("ui-state docs smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
