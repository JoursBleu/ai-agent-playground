#!/usr/bin/env python3
"""Verify a deployed Agent Playground health endpoint.

Usage:
  python3 scripts/verify_deploy_health.py [base_url] [expected_commit_prefix]

Examples:
  python3 scripts/verify_deploy_health.py https://agent-playground.space ef55d45
"""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    url = f"{base_url}/api/health"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw-Deploy-Health/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if data.get("ok") is not True:
        raise SystemExit(f"health not ok: {data!r}")
    version = data.get("version") or {}
    commit = str(version.get("commit") or "")
    if not commit:
        raise SystemExit(f"missing version.commit in health response: {data!r}")
    if expected and not commit.startswith(expected):
        raise SystemExit(f"commit mismatch: expected prefix {expected!r}, got {commit!r}")
    print(json.dumps({"ok": True, "url": url, "commit": commit, "source": version.get("source")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
