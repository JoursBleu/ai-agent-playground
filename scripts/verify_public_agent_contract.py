#!/usr/bin/env python3
"""Verify public Agent Playground agent-facing read contracts.

By default this script avoids mutating state. It checks:
- /api/health exposes deployed commit/version
- /api/capabilities exposes machine-readable endpoint discovery
- /api/games is reachable
- /ui-state, /action-schema, and /events expose compatible schema_version
  and event_log/events contracts when a public room exists.

Usage:
  python3 scripts/verify_public_agent_contract.py [base_url] [expected_commit_prefix]

Environment:
  AAP_VERIFY_CREATE_DEMO=1  Create a waiting demo room when no public room exists.
  AAP_VERIFY_KEY=aap_...    Bearer API key used for optional demo room creation.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

UA = "OpenClaw-Agent-Contract-Verify/1.0"


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, payload: dict, *, bearer: str = "") -> dict:
    headers = {"User-Agent": UA, "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def maybe_create_demo_room(base: str) -> dict:
    """Create a short-lived public waiting room only when explicitly enabled."""
    if not env_enabled("AAP_VERIFY_CREATE_DEMO"):
        return {"created": False, "reason": "demo creation disabled"}
    key = os.getenv("AAP_VERIFY_KEY", "").strip()
    if not key:
        return {"created": False, "reason": "AAP_VERIFY_KEY missing"}
    payload = {
        "name": "agent-contract-demo",
        "description": "temporary contract verifier room",
        "game_type": "doudizhu",
        "rule_mode": "builtin",
    }
    try:
        resp = post_json(f"{base}/api/games", payload, bearer=key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"created": False, "reason": f"create failed: HTTP {exc.code} {detail}"}
    gid = resp.get("game_id")
    if not gid:
        return {"created": False, "reason": f"create response missing game_id: {resp!r}"}
    return {"created": True, "game_id": gid, "game_type": resp.get("game_type")}


def verify_action_contract(ui_actions: list, actions_actions: list, schema_actions: list) -> dict:
    """Validate visible action handles against the durable action schema."""
    if actions_actions != ui_actions:
        raise SystemExit(f"actions != ui-state actions: actions={actions_actions!r}, ui={ui_actions!r}")
    schema_action_ids = [a.get("id") for a in schema_actions]
    visible_action_ids = [a.get("id") for a in actions_actions]
    visible_action_signatures = [
        json.dumps({"id": a.get("id"), "params": a.get("params") or {}}, sort_keys=True)
        for a in actions_actions
    ]
    schema_ids = set(schema_action_ids)
    visible_ids = set(visible_action_ids)
    if len(schema_action_ids) != len(schema_ids):
        raise SystemExit(f"duplicate schema action ids: {schema_action_ids!r}")
    if len(visible_action_signatures) != len(set(visible_action_signatures)):
        raise SystemExit(f"duplicate visible action signatures: {visible_action_signatures!r}")
    missing_schema_ids = sorted(visible_ids - schema_ids)
    if missing_schema_ids:
        raise SystemExit(f"visible actions missing from schema: {missing_schema_ids!r}")
    return {
        "action_count": len(ui_actions),
        "schema_action_count": len(schema_actions),
    }


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
    if not isinstance(ui.get("actions"), list):
        raise SystemExit(f"ui-state missing actions list: {ui!r}")
    if not isinstance(schema.get("actions"), list):
        raise SystemExit(f"schema missing actions list: {schema!r}")
    action_summary = verify_action_contract(
        ui_actions=ui.get("actions"),
        actions_actions=actions.get("actions"),
        schema_actions=schema.get("actions"),
    )
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
        **action_summary,
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

    demo_room = {"created": False}
    room_contract = {
        "covered": False,
        "game_id": None,
        "skipped_reason": "no public games",
    }
    if not games:
        demo_room = maybe_create_demo_room(base)
        if demo_room.get("created"):
            games_resp = get_json(f"{base}/api/games")
            games = games_resp.get("games") if isinstance(games_resp, dict) else []
            if not isinstance(games, list):
                raise SystemExit(f"bad games response after demo create: {games_resp!r}")
        else:
            room_contract["skipped_reason"] = str(demo_room.get("reason") or "no public games")

    if games:
        gid = demo_room.get("game_id") or games[0].get("game_id") or games[0].get("id")
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
            "demo_room": demo_room,
        },
        # Backward-compatible summary fields for humans/scripts that grep output.
        "games_count": len(games),
        "checked_game": room_contract.get("game_id"),
        "skipped_contract_reason": room_contract.get("skipped_reason"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
