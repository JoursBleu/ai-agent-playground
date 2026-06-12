#!/usr/bin/env python3
"""Check public docs/front-end do not reintroduce legacy /state guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_GLOBS = [
    "README.md",
    "docs/**/*.md",
    "research/**/*.md",
    "backend/static/js/*.js",
    "backend/static/index.html",
]
ALLOWED_STATE_MENTIONS = {
    "docs/AGENT_API.md": ["legacy `/state`"],
    "research/understand-anything-repo-study-2026-06-10.md": [
        "Keep deterministic extraction/state/action schemas first",
    ],
    "research/agent-readable-game-api-patterns-2026-06-11.md": [
        "migrating the front end away from `/state` and toward `/ui-state`",
        "Replace any remaining direct `/state` UI reads with `/ui-state`.",
        "match `ui_state.actions` for the same token/state.",
    ],
}


def iter_check_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in CHECK_GLOBS:
        paths.update(ROOT.glob(pattern))
    return sorted(p for p in paths if p.is_file())


def main() -> int:
    for path in iter_check_paths():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
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
