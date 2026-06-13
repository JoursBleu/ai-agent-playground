#!/usr/bin/env python3
"""Check browser action buttons use the unified /action handle.

Legacy game-specific mutation endpoints are kept only for compatibility; UI code
should call gameAction(), which posts to POST /api/games/{game_id}/action.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = [
    "${gameId}/bid",
    "${gameId}/play",
    "${gameId}/zjh/action",
    "${gameId}/texas/action",
]
CHECK_GLOBS = [
    "backend/static/js/*.js",
    "backend/static/index.html",
]


def main() -> int:
    for pattern in CHECK_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT).as_posix()
            for line_no, line in enumerate(text.splitlines(), 1):
                for forbidden in FORBIDDEN:
                    if forbidden in line:
                        raise SystemExit(f"legacy frontend action endpoint {forbidden!r} in {rel}:{line_no}: {line}")
    app_js = (ROOT / "backend/static/js/app.js").read_text(encoding="utf-8")
    if "function gameAction" not in app_js or "/api/games/${gameId}/action" not in app_js:
        raise SystemExit("missing unified gameAction() helper")
    required_action_handles = {
        "backend/static/js/app.js": [
            "data-action-id",
            "data-action-enabled",
            "data-disabled-reason",
        ],
        "backend/static/js/doudizhu-ui.js": [
            "actionById.get('bid')",
            "dataset.actionId = 'bid'",
            "['play_cards', 'pass', 'play_hint']",
            "dataset.actionId = id",
            "dataset.actionEnabled",
        ],
        "backend/static/js/texas-ui.js": [
            "dataset.actionId",
            "dataset.actionEnabled",
            "dataset.disabledReason",
            "dataset.actionParamAmount",
            "dataset.actionParamCallAmount",
            "dataset.actionParamRaiseMin",
            "dataset.actionParamRaiseMax",
            "dataset.actionParamMin",
            "dataset.actionParamMax",
            "data-action-id",
            "data-action-enabled",
            "data-disabled-reason",
        ],
    }
    for rel, snippets in required_action_handles.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                raise SystemExit(f"missing frontend machine-readable action handle {snippet!r} in {rel}")
    print("unified frontend actions smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
