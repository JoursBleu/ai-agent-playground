#!/usr/bin/env python3
"""Dependency-free smoke checks for public verifier helper logic."""

from __future__ import annotations

import os
from contextlib import contextmanager

from verify_public_agent_contract import env_enabled, maybe_create_demo_room
from verify_public_deploy import slow_checks, slow_threshold_ms


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


def main() -> int:
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

    print("public verifier helper smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
