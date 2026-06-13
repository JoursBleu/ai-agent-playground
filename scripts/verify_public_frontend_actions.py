#!/usr/bin/env python3
"""Verify deployed static frontend exposes machine-readable action handles.

This is read-only and checks the public static JS served by the deployment, not
just the local source tree. It complements smoke_unified_frontend_actions.py.

Usage:
  python3 scripts/verify_public_frontend_actions.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request

UA = "OpenClaw-Frontend-Actions-Verify/1.0"

CHECKS = {
    "/static/js/app.js": [
        "data-action-id",
        "data-action-enabled",
        "data-disabled-reason",
        "/api/games/${gameId}/action",
    ],
    "/static/js/doudizhu-ui.js": [
        "actionById.get('bid')",
        "dataset.actionId = 'bid'",
        "['play_cards', 'pass', 'play_hint']",
        "dataset.actionId = id",
        "dataset.actionEnabled",
    ],
    "/static/js/texas-ui.js": [
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

FORBIDDEN = [
    "${gameId}/bid",
    "${gameId}/play",
    "${gameId}/zjh/action",
    "${gameId}/texas/action",
]


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing {label}: {needle!r}")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")
    checked: list[str] = []
    for path, needles in CHECKS.items():
        text = get_text(f"{base}{path}")
        for forbidden in FORBIDDEN:
            if forbidden in text:
                raise SystemExit(f"legacy frontend action endpoint {forbidden!r} in deployed {path}")
        for needle in needles:
            require(text, needle, f"deployed {path}")
        checked.append(path)
    print(json.dumps({"ok": True, "base": base, "checks": checked}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
