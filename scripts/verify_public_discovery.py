#!/usr/bin/env python3
"""Verify public SEO/discovery surfaces for Agent Playground.

Checks are intentionally read-only:
- homepage title/description/canonical/OpenGraph metadata
- agent-facing landing copy
- /robots.txt points to the sitemap
- /sitemap.xml lists the homepage, Agent API docs, health, and capabilities endpoints

Usage:
  python3 scripts/verify_public_discovery.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request

UA = "OpenClaw-Discovery-Verify/1.0"


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing {label}: {needle!r}")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://agent-playground.space").rstrip("/")

    home = get_text(f"{base}/")
    require(home, "AgentPlayground — HTTP-native multi-agent game arena", "homepage title")
    require(home, '<meta name="description"', "meta description")
    require(home, 'property="og:title"', "og:title")
    require(home, 'property="og:description"', "og:description")
    require(home, '<link rel="canonical" href="https://agent-playground.space/"', "canonical URL")
    require(home, "HTTP-native multi-agent game arena", "agent landing hero")
    require(home, "Agent capabilities JSON", "agent capabilities CTA")
    require(home, "/api/capabilities", "capabilities link")
    require(home, "/api/games/{id}/ui-state", "agent quickstart")

    robots = get_text(f"{base}/robots.txt")
    require(robots, "User-agent: *", "robots user-agent")
    require(robots, "Allow: /", "robots allow")
    require(robots, "Sitemap: https://agent-playground.space/sitemap.xml", "robots sitemap")

    sitemap = get_text(f"{base}/sitemap.xml")
    for loc in [
        "https://agent-playground.space/",
        "https://agent-playground.space/docs-agent",
        "https://agent-playground.space/api/health",
        "https://agent-playground.space/api/capabilities",
    ]:
        require(sitemap, f"<loc>{loc}</loc>", f"sitemap loc {loc}")

    print(json.dumps({"ok": True, "base": base, "checks": ["homepage", "robots", "sitemap"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
