#!/usr/bin/env python3
"""Dependency-free smoke checks for public verifier helper logic."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from verify_public_agent_contract import env_enabled, maybe_create_demo_room, verify_action_contract, verify_legacy_docs
from verify_public_deploy import slow_checks, slow_threshold_ms
from verify_public_frontend_actions import CHECKS as FRONTEND_ACTION_CHECKS, FORBIDDEN as FRONTEND_ACTION_FORBIDDEN

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def env_var(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def assert_exits(fn, needle: str) -> None:
    try:
        fn()
    except SystemExit as exc:
        assert needle in str(exc), exc
        return
    raise AssertionError("expected SystemExit")


def test_slow_threshold_helpers() -> None:
    with env_var("AAP_VERIFY_SLOW_MS", None):
        assert slow_threshold_ms() == 5000
    with env_var("AAP_VERIFY_SLOW_MS", "0"):
        assert slow_threshold_ms() == 0
    with env_var("AAP_VERIFY_SLOW_MS", "2500"):
        assert slow_threshold_ms() == 2500
    with env_var("AAP_VERIFY_SLOW_MS", "abc"):
        assert_exits(slow_threshold_ms, "must be an integer")
    with env_var("AAP_VERIFY_SLOW_MS", "-1"):
        assert_exits(slow_threshold_ms, "must be >= 0")

    assert slow_checks({"a": 10, "b": 5, "c": 4}, 5) == [
        {"check": "a", "duration_ms": 10, "threshold_ms": 5},
        {"check": "b", "duration_ms": 5, "threshold_ms": 5},
    ]



def test_optional_demo_flags() -> None:
    with env_var("AAP_VERIFY_CREATE_DEMO", None):
        assert env_enabled("AAP_VERIFY_CREATE_DEMO") is False
        assert maybe_create_demo_room("https://example.invalid") == {
            "created": False,
            "reason": "demo creation disabled",
        }
    for value in ("1", "true", "yes", "on"):
        with env_var("AAP_VERIFY_CREATE_DEMO", value), env_var("AAP_VERIFY_KEY", None):
            assert env_enabled("AAP_VERIFY_CREATE_DEMO") is True
            assert maybe_create_demo_room("https://example.invalid") == {
                "created": False,
                "reason": "AAP_VERIFY_KEY missing",
            }
    with env_var("AAP_VERIFY_CREATE_DEMO", "0"):
        assert env_enabled("AAP_VERIFY_CREATE_DEMO") is False



def test_legacy_docs_helper() -> None:
    caps = {
        "legacy_endpoints": {
            "state": {"replacement": "/api/games/{game_id}/ui-state"},
            "bid": {"replacement": "/api/games/{game_id}/action"},
            "play": {"replacement": "/api/games/{game_id}/action"},
        }
    }
    docs = """
    legacy_endpoints.state.replacement = /api/games/{game_id}/ui-state
    legacy_endpoints.bid/play.replacement = /api/games/{game_id}/action
    """
    assert verify_legacy_docs(caps, docs)["ok"] is True
    assert_exits(lambda: verify_legacy_docs(caps, ""), "docs missing legacy replacement")
    bad_caps = {
        "legacy_endpoints": {
            "state": {"replacement": "/api/games/{game_id}/ui-state"},
            "bid": {"replacement": "/api/games/{game_id}/action"},
            "play": {"replacement": "/api/games/{game_id}/play"},
        }
    }
    assert_exits(lambda: verify_legacy_docs(bad_caps, docs), "legacy bid/play replacement mismatch")



def test_preflight_mentions_unified_frontend_actions() -> None:
    command = "python3 scripts/smoke_unified_frontend_actions.py"
    script = ROOT / "scripts/smoke_unified_frontend_actions.py"
    assert script.exists(), script
    for rel in ("README.md", "docs/DEPLOYMENT.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert command in text, f"{rel} missing {command}"



def test_deployed_frontend_actions_verifier_is_wired() -> None:
    command = "python3 scripts/verify_public_frontend_actions.py https://agent-playground.space"
    script = ROOT / "scripts/verify_public_frontend_actions.py"
    deploy = (ROOT / "scripts/verify_public_deploy.py").read_text(encoding="utf-8")
    assert script.exists(), script
    assert "verify_public_frontend_actions.py" in deploy
    assert "deployed_frontend_actions" in deploy
    for rel in ("README.md", "docs/DEPLOYMENT.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert command in text, f"{rel} missing {command}"
    assert set(FRONTEND_ACTION_CHECKS) == {
        "/static/js/app.js",
        "/static/js/doudizhu-ui.js",
        "/static/js/texas-ui.js",
    }
    for needles in FRONTEND_ACTION_CHECKS.values():
        assert any("action" in needle for needle in needles), needles
    assert "${gameId}/bid" in FRONTEND_ACTION_FORBIDDEN
    assert "${gameId}/texas/action" in FRONTEND_ACTION_FORBIDDEN



def test_action_contract_helper() -> None:
    ui_actions = [
        {"id": "bid", "enabled": True, "params": {"bid": 1}},
        {"id": "bid", "enabled": True, "params": {"bid": 2}},
    ]
    assert verify_action_contract(
        ui_actions=ui_actions,
        actions_actions=list(ui_actions),
        schema_actions=[{"id": "bid", "params": {"bid": "integer"}}],
    ) == {"action_count": 2, "schema_action_count": 1}
    assert_exits(
        lambda: verify_action_contract(
            ui_actions=ui_actions,
            actions_actions=[ui_actions[0]],
            schema_actions=[{"id": "bid", "params": {"bid": "integer"}}],
        ),
        "actions != ui-state actions",
    )
    assert_exits(
        lambda: verify_action_contract(
            ui_actions=ui_actions,
            actions_actions=list(ui_actions),
            schema_actions=[{"id": "bid"}, {"id": "bid"}],
        ),
        "duplicate schema action ids",
    )
    assert_exits(
        lambda: verify_action_contract(
            ui_actions=[ui_actions[0], ui_actions[0]],
            actions_actions=[ui_actions[0], ui_actions[0]],
            schema_actions=[{"id": "bid"}],
        ),
        "duplicate visible action signatures",
    )
    assert_exits(
        lambda: verify_action_contract(
            ui_actions=[{"id": "pass", "params": {}}],
            actions_actions=[{"id": "pass", "params": {}}],
            schema_actions=[{"id": "bid"}],
        ),
        "visible actions missing from schema",
    )


def main() -> int:
    test_slow_threshold_helpers()
    test_optional_demo_flags()
    test_legacy_docs_helper()
    test_preflight_mentions_unified_frontend_actions()
    test_deployed_frontend_actions_verifier_is_wired()
    test_action_contract_helper()
    print("public verifier helper smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
