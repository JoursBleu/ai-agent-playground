#!/usr/bin/env python3
"""Run the full read-only public deploy verification suite.

This wraps the individual public verifiers so post-deploy checks are one
command while still keeping each focused script usable on its own.

Usage:
  python3 scripts/verify_public_deploy.py [base_url] [expected_commit_prefix]

Environment:
  AAP_VERIFY_SLOW_MS  Slow-check threshold in milliseconds (default: 5000).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SLOW_CHECK_THRESHOLD_MS = 5000


def slow_threshold_ms() -> int:
    raw = os.getenv("AAP_VERIFY_SLOW_MS", "").strip()
    if not raw:
        return DEFAULT_SLOW_CHECK_THRESHOLD_MS
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"AAP_VERIFY_SLOW_MS must be an integer milliseconds value, got {raw!r}") from exc
    if value < 0:
        raise SystemExit(f"AAP_VERIFY_SLOW_MS must be >= 0, got {value}")
    return value


def run_text(cmd: list[str]) -> tuple[str, int]:
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    duration_ms = round((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"duration_ms: {duration_ms}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc.stdout, duration_ms


def run_json(cmd: list[str]) -> tuple[dict, int]:
    stdout, duration_ms = run_text(cmd)
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"command produced no JSON output: {' '.join(cmd)}")
    try:
        return json.loads(lines[-1]), duration_ms
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse JSON from {' '.join(cmd)}: {exc}\nstdout:\n{stdout}") from exc


def slow_checks(durations: dict[str, int], threshold_ms: int) -> list[dict]:
    return [
        {"check": name, "duration_ms": duration, "threshold_ms": threshold_ms}
        for name, duration in sorted(durations.items())
        if duration >= threshold_ms
    ]


def main() -> int:
    suite_started = time.monotonic()
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    py = sys.executable or "python3"

    health_cmd = [py, "scripts/verify_deploy_health.py", base]
    contract_cmd = [py, "scripts/verify_public_agent_contract.py", base]
    if expected:
        health_cmd.append(expected)
        contract_cmd.append(expected)

    frontend_stdout, frontend_ms = run_text([py, "scripts/smoke_unified_frontend_actions.py"])
    if "unified frontend actions smoke: ok" not in frontend_stdout:
        raise SystemExit(f"unexpected frontend action smoke output: {frontend_stdout!r}")
    health, health_ms = run_json(health_cmd)
    contract, contract_ms = run_json(contract_cmd)
    discovery, discovery_ms = run_json([py, "scripts/verify_public_discovery.py", base])

    commit = health.get("commit") or contract.get("commit")
    if expected and not str(commit).startswith(expected):
        raise SystemExit(f"commit mismatch after suite: expected {expected!r}, got {commit!r}")

    durations = {
        "frontend_actions": frontend_ms,
        "health": health_ms,
        "agent_contract": contract_ms,
        "discovery": discovery_ms,
    }
    total_ms = round((time.monotonic() - suite_started) * 1000)
    threshold_ms = slow_threshold_ms()

    print(json.dumps({
        "ok": True,
        "base": base,
        "commit": commit,
        "duration_ms": total_ms,
        "slow_threshold_ms": threshold_ms,
        "slow_checks": slow_checks(durations, threshold_ms),
        "checks": {
            "frontend_actions": {"ok": True, "duration_ms": frontend_ms},
            "health": {**health, "duration_ms": health_ms},
            "agent_contract": {**contract, "duration_ms": contract_ms},
            "discovery": {**discovery, "duration_ms": discovery_ms},
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
