#!/usr/bin/env python3
"""Verify public Agent Playground agent-facing read contracts.

This script intentionally avoids mutating state. It checks:
- /api/health exposes deployed commit/version
- /api/capabilities exposes machine-readable endpoint discovery
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

UA = "OpenClaw-Agent-Contract-Verify/1.0"


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_room_contract(base: str, gid: str) -> dict:
    ui = get_json(f"{base}/api/games/{gid}/ui-state")
    actions = get_json(f"{base}/api/games/{gid}/actions")
    schema = get_json(f"{base}/api/games/{gid}/action-schema")
    events = get_json(f"{base}/api/games/{gid}/events")
    if not ui.get("schema_version"):
        raise SystemExit(f"ui-state missing schema_version: {ui!r}")
    if actions.get("schema_version") != ui.get("schema_version"):
        raise SystemExit(
            f"actions schema_version mismatch: ui={ui.get('schema_version')!r}, "
            f"actions={actions.get('schema_version')!r}"
        )
    if not isinstance(actions.get("actions"), list):
        raise SystemExit(f"actions missing actions list: {actions!r}")
    if schema.get("schema_version") != ui.get("schema_version"):
        raise SystemExit(
            f"schema_version mismatch: ui={ui.get('schema_version')!r}, "
            f"schema={schema.get('schema_version')!r}"
        )
    if events.get("schema_version") != ui.get("schema_version"):
        raise SystemExit(
            f"events schema_version mismatch: ui={ui.get('schema_version')!r}, "
            f"events={events.get('schema_version')!r}"
        )
    if "event_log" not in ui or not isinstance(ui.get("event_log"), list):
        raise SystemExit(f"ui-state missing event_log list: {ui!r}")
    if events.get("events") != ui.get("event_log"):
        raise SystemExit(f"events != ui-state event_log: events={events!r}, ui={ui!r}")
    expected_events_endpoint = f"/api/games/{gid}/events"
    if schema.get("events_endpoint") != expected_events_endpoint:
        raise SystemExit(
            f"bad events_endpoint: expected {expected_events_endpoint!r}, "
            f"got {schema.get('events_endpoint')!r}"
        )
    return {
        "covered": True,
        "game_id": gid,
        "schema_version": ui.get("schema_version"),
        "event_count": len(ui.get("event_log") or []),
        "endpoints": ["ui-state", "actions", "action-schema", "events"],
    }


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

    caps = get_json(f"{base}/api/capabilities")
    if caps.get("schema_version") is None:
        raise SystemExit(f"capabilities missing schema_version: {caps!r}")
    endpoints = caps.get("endpoints") or {}
    for key in ["ui_state", "actions", "action_schema", "events", "execute_action"]:
        if key not in endpoints:
            raise SystemExit(f"capabilities missing endpoint {key!r}: {caps!r}")
    maintenance = caps.get("maintenance") or {}
    if "verify_public_deploy.py" not in str(maintenance.get("public_verify_command") or ""):
        raise SystemExit(f"capabilities missing public verify command: {caps!r}")

    games_resp = get_json(f"{base}/api/games")
    games = games_resp.get("games") if isinstance(games_resp, dict) else None
    if not isinstance(games, list):
        raise SystemExit(f"bad games response: {games_resp!r}")

    room_contract = {
        "covered": False,
        "game_id": None,
        "skipped_reason": "no public games",
    }
    if games:
        gid = games[0].get("game_id") or games[0].get("id")
        if not gid:
            room_contract["skipped_reason"] = "first public game missing id"
        else:
            room_contract = verify_room_contract(base, gid)

    print(json.dumps({
        "ok": True,
        "base": base,
        "commit": commit,
        "checks": {
            "health": {"ok": True, "commit": commit, "source": version.get("source")},
            "capabilities": {"ok": True, "schema_version": caps.get("schema_version"), "endpoints": sorted(endpoints), "maintenance": sorted(maintenance)},
            "games": {"ok": True, "count": len(games)},
            "room_contract": room_contract,
        },
        # Backward-compatible summary fields for humans/scripts that grep output.
        "games_count": len(games),
        "checked_game": room_contract.get("game_id"),
        "skipped_contract_reason": room_contract.get("skipped_reason"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
