#!/usr/bin/env python3
"""Run the full read-only public deploy verification suite.

This wraps the individual public verifiers so post-deploy checks are one
command while still keeping each focused script usable on its own.

Usage:
  python3 scripts/verify_public_deploy.py [base_url] [expected_commit_prefix]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"command produced no JSON output: {' '.join(cmd)}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse JSON from {' '.join(cmd)}: {exc}\nstdout:\n{proc.stdout}") from exc


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    py = sys.executable or "python3"

    health_cmd = [py, "scripts/verify_deploy_health.py", base]
    contract_cmd = [py, "scripts/verify_public_agent_contract.py", base]
    if expected:
        health_cmd.append(expected)
        contract_cmd.append(expected)

    health = run_json(health_cmd)
    contract = run_json(contract_cmd)
    discovery = run_json([py, "scripts/verify_public_discovery.py", base])

    commit = health.get("commit") or contract.get("commit")
    if expected and not str(commit).startswith(expected):
        raise SystemExit(f"commit mismatch after suite: expected {expected!r}, got {commit!r}")

    print(json.dumps({
        "ok": True,
        "base": base,
        "commit": commit,
        "checks": {
            "health": health,
            "agent_contract": contract,
            "discovery": discovery,
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
