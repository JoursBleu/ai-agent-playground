#!/usr/bin/env python3
"""Verify public Agent Playground agent-facing read contracts.

This script intentionally avoids mutating state. It checks:
- /api/health exposes deployed commit/version
- /api/games is reachable
- /ui-state, /action-schema, and /events expose compatible schema_version
  and event_log/events contracts when a public room exists.

Usage:
  python3 scripts/verify_public_agent_contract.py [base_url] [expected_commit_prefix]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from urllib.error import HTTPError

UA = "OpenClaw-Agent-Contract-Verify/1.0"


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    health = get_json(f"{base}/api/health")
    version = health.get("version") or {}
    commit = str(version.get("commit") or "")
    if health.get("ok") is not True or not commit:
        raise SystemExit(f"bad health response: {health!r}")
    if expected and not commit.startswith(expected):
        raise SystemExit(f"commit mismatch: expected {expected!r}, got {commit!r}")

    games_resp = get_json(f"{base}/api/games")
    games = games_resp.get("games") if isinstance(games_resp, dict) else None
    if not isinstance(games, list):
        raise SystemExit(f"bad games response: {games_resp!r}")

    checked_game = None
    skipped_contract_reason = "no public games"
    if games:
        gid = games[0].get("game_id") or games[0].get("id")
        if gid:
            ui = get_json(f"{base}/api/games/{gid}/ui-state")
            schema = get_json(f"{base}/api/games/{gid}/action-schema")
            events = get_json(f"{base}/api/games/{gid}/events")
            if not ui.get("schema_version"):
                raise SystemExit(f"ui-state missing schema_version: {ui!r}")
            if schema.get("schema_version") != ui.get("schema_version"):
                raise SystemExit(f"schema_version mismatch: ui={ui.get('schema_version')!r}, schema={schema.get('schema_version')!r}")
            if events.get("schema_version") != ui.get("schema_version"):
                raise SystemExit(f"events schema_version mismatch: ui={ui.get('schema_version')!r}, events={events.get('schema_version')!r}")
            if "event_log" not in ui or not isinstance(ui.get("event_log"), list):
                raise SystemExit(f"ui-state missing event_log list: {ui!r}")
            if events.get("events") != ui.get("event_log"):
                raise SystemExit(f"events != ui-state event_log: events={events!r}, ui={ui!r}")
            expected_events_endpoint = f"/api/games/{gid}/events"
            if schema.get("events_endpoint") != expected_events_endpoint:
                raise SystemExit(f"bad events_endpoint: expected {expected_events_endpoint!r}, got {schema.get('events_endpoint')!r}")
            checked_game = gid
            skipped_contract_reason = None

    print(json.dumps({
        "ok": True,
        "base": base,
        "commit": commit,
        "games_count": len(games),
        "checked_game": checked_game,
        "skipped_contract_reason": skipped_contract_reason,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
