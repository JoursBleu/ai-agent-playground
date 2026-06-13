# Launch Readiness

Date: 2026-06-13
Branch: `business`
Production: <https://agent-playground.space>
Current verified commit: `304b9dda3fd1`

## Status

Ready for launch-prep / final packaging.

The current production build has passed the read-only public verification suite. Legacy compatibility endpoints are still present for old clients, but public docs, README quickstart, browser UI, and agent-facing discovery now point to the `/ui-state` + unified `/action` contract.

## Final verified command

```bash
python3 scripts/verify_public_deploy.py https://agent-playground.space 304b9dd
```

Expected high-level result:

```json
{
  "ok": true,
  "commit": "304b9dda3fd1",
  "checks": {
    "frontend_actions": {"ok": true},
    "deployed_frontend_actions": {"ok": true},
    "health": {"ok": true},
    "agent_contract": {"ok": true},
    "discovery": {"ok": true}
  }
}
```

## Launch-facing contract summary

- Primary state read: `GET /api/games/{game_id}/ui-state?token=...`
- Current legal actions: `GET /api/games/{game_id}/actions?token=...`
- Stable action schema: `GET /api/games/{game_id}/action-schema`
- Event/replay trace: `GET /api/games/{game_id}/events?token=...`
- Unified mutation endpoint: `POST /api/games/{game_id}/action`
- Browser automation surface: `data-action-*` and `data-action-param-*` attributes projected from `/ui-state.actions`.

## Closed before launch

- README quickstart no longer teaches legacy `/bid` or `/play`; examples use unified `/action`.
- `/api/capabilities.endpoints` no longer lists the legacy state endpoint as a primary endpoint.
- Legacy endpoint replacements remain documented under `/api/capabilities.legacy_endpoints`.
- Route-layer `action_descriptors(game, ...)` helper seam was removed; routes call `GameInterface.action_descriptors(...)` directly.
- `GameInterface.apply_action(...)` owns unified action dispatch; route layer stays thin.
- Public deploy verifier now checks deployed static JS for browser-agent action handles.
- Deployed-static verifier uses cache-busting to avoid Cloudflare stale JS false negatives.

## Known non-blocking notes

- `slow_checks` may appear for `agent_contract`, `deployed_frontend_actions`, or `discovery` during public verification. Treat this as network/CDN latency unless `ok` is false.
- A transient `/docs-agent` 502 was observed once during verification; immediate manual curl returned 200 and the full suite passed on rerun.
- Demo-room contract coverage is read-only by default. `room_contract.covered=false` with `skipped_reason="demo creation disabled"` is expected unless `AAP_VERIFY_CREATE_DEMO=1` and `AAP_VERIFY_KEY` are intentionally provided.

## Pre-launch quick checklist

```bash
git status --short
python3 scripts/smoke_agent_api_contract.py
python3 scripts/smoke_public_deploy_verifier.py
python3 scripts/smoke_ui_state_docs.py
python3 scripts/smoke_unified_frontend_actions.py
python3 scripts/verify_public_frontend_actions.py https://agent-playground.space
python3 -m compileall -q backend scripts
for f in backend/static/js/*.js; do node --check "$f" || exit 1; done
python3 scripts/verify_public_deploy.py https://agent-playground.space <commit-prefix>
```

## Rollback pointer

Use `docs/DEPLOYMENT.md` rollback section. The previous known-good production commits immediately before this closure sequence include:

- `b1514d0` — documented Dou Dizhu DOM action params.
- `1fcc531` — exposed Dou Dizhu action parameter handles.
- `82d5c47` — documented browser action handle surface.
