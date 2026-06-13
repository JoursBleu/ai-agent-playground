# Deployment Runbook

Production site: <https://agent-playground.space>  
Production host: `latex-tools`  
Repo branch: `business`  
App path: `/opt/ai-agent-playground`

This runbook is intentionally operational and short. The goal is a repeatable loop:

```text
self-check -> commit -> push -> deploy -> public verify -> rollback plan ready
```

## 1. Local preflight

From the repo root:

```bash
python3 scripts/smoke_agent_api_contract.py
python3 scripts/smoke_public_deploy_verifier.py
python3 scripts/smoke_ui_state_docs.py
python3 scripts/smoke_unified_frontend_actions.py
python3 -m compileall -q backend scripts
for f in backend/static/js/*.js; do node --check "$f" || exit 1; done
```

Optional pre-deploy baseline:

```bash
python3 scripts/verify_public_deploy.py https://agent-playground.space <current-live-commit-prefix>
```

Individual checks remain useful while debugging:

```bash
python3 scripts/verify_deploy_health.py https://agent-playground.space <current-live-commit-prefix>
python3 scripts/verify_public_frontend_actions.py https://agent-playground.space
python3 scripts/verify_public_agent_contract.py https://agent-playground.space <current-live-commit-prefix>
python3 scripts/verify_public_discovery.py https://agent-playground.space
```

## 2. Commit and push

```bash
git status --short
git diff --check
git add <changed-files>
git commit -m "..."
GIT_SSH_COMMAND='ssh -i /home/node/.openclaw/workspace/docs/ssh/id_rsa -o UserKnownHostsFile=/home/node/.openclaw/workspace/docs/ssh/known_hosts -o StrictHostKeyChecking=accept-new' \
  git push git@github.com:JoursBleu/ai-agent-playground.git business
```

## 3. Deploy to latex-tools

Use the docs SSH key explicitly. `ssh -F docs/ssh/config latex-tools` may fail to pass the key through the jump host; this explicit ProxyCommand is the known-good form from OpenClaw:

```bash
ssh \
  -i /home/node/.openclaw/workspace/docs/ssh/id_rsa \
  -o UserKnownHostsFile=/home/node/.openclaw/workspace/docs/ssh/known_hosts \
  -o StrictHostKeyChecking=accept-new \
  -o ProxyCommand="ssh -i /home/node/.openclaw/workspace/docs/ssh/id_rsa -o UserKnownHostsFile=/home/node/.openclaw/workspace/docs/ssh/known_hosts -o StrictHostKeyChecking=accept-new -W %h:%p root@82.156.115.203" \
  root@107.174.178.57 \
  'set -e; cd /opt/ai-agent-playground; git pull --ff-only; systemctl restart ai-agent-playground; for i in 1 2 3 4 5; do curl -fsS -m 10 http://127.0.0.1:8765/api/health && break || sleep 1; done; echo; git rev-parse --short=12 HEAD; systemctl is-active ai-agent-playground'
```

If git reports dubious ownership once on the server:

```bash
git config --global --add safe.directory /opt/ai-agent-playground
```

## 4. Public verification

After deploy, verify health/version, deployed static frontend action handles, read-only agent contract, and public discovery surfaces:

```bash
python3 scripts/verify_public_deploy.py https://agent-playground.space <new-commit-prefix>
```

Individual checks remain useful while debugging:

```bash
python3 scripts/verify_deploy_health.py https://agent-playground.space <new-commit-prefix>
python3 scripts/verify_public_frontend_actions.py https://agent-playground.space
python3 scripts/verify_public_agent_contract.py https://agent-playground.space <new-commit-prefix>
python3 scripts/verify_public_discovery.py https://agent-playground.space
```

When no public room exists, the agent contract check stays read-only by default and reports `demo_room.created=false`. To force full room-contract coverage, provide a short-lived verifier API key and explicitly allow demo room creation:

```bash
AAP_VERIFY_CREATE_DEMO=1 AAP_VERIFY_KEY="$AAP_KEY" \
  python3 scripts/verify_public_agent_contract.py https://agent-playground.space <new-commit-prefix>
```

Expected combined verification shape:

```json
{
  "ok": true,
  "base": "https://agent-playground.space",
  "commit": "<new commit>",
  "duration_ms": 8000,
  "slow_threshold_ms": 5000,
  "slow_checks": [],
  "checks": {
    "frontend_actions": {"ok": true, "duration_ms": 25},
    "deployed_frontend_actions": {"ok": true, "duration_ms": 1800},
    "health": {"ok": true, "duration_ms": 1200},
    "agent_contract": {"ok": true, "duration_ms": 3200},
    "discovery": {"ok": true, "duration_ms": 3600}
  }
}
```

`frontend_actions` is a local preflight inside the public deploy verifier. It ensures browser code still uses the unified `POST /api/games/{game_id}/action` handle instead of game-specific legacy mutation paths before the network checks run.

`deployed_frontend_actions` fetches the public static JS (`/static/js/app.js`, `/static/js/doudizhu-ui.js`, `/static/js/texas-ui.js`) and confirms deployed browser code exposes machine-readable action handles such as `data-action-id`, `data-action-enabled`, and `data-disabled-reason`.

`duration_ms` is informational. Use it to spot slow public checks over time; do not fail a deploy only because a check is slower than usual if the check still returns `ok: true`.

`slow_checks` lists sub-checks whose duration is at or above `slow_threshold_ms` (default 5000 ms). Override the threshold for CI or local debugging with `AAP_VERIFY_SLOW_MS=<milliseconds>`. Treat it as an operations hint for monitoring and investigation, not as a failure signal by itself.

## 5. Rollback

If public verification fails after a deploy, rollback to the previous known-good commit.

On latex-tools:

```bash
cd /opt/ai-agent-playground
git log --oneline -5
git reset --hard <previous-good-commit>
systemctl restart ai-agent-playground
curl -fsS -m 10 http://127.0.0.1:8765/api/health
```

Then verify publicly from the workspace:

```bash
python3 scripts/verify_public_deploy.py https://agent-playground.space <previous-good-prefix>
```

Only force-push/revert the remote branch after deciding whether the bad commit should be reverted in git history. Prefer a normal revert commit when possible:

```bash
git revert <bad-commit>
git push origin business
```

## 6. Known operational notes

- `agent-playground.space` is behind Cloudflare.
- Python urllib with default User-Agent can be blocked by Cloudflare; verifier scripts set explicit User-Agent.
- `/api/health` includes `version.commit`, so public deploy verification does not require SSH.
- The nginx site symlink must exist: `/etc/nginx/sites-enabled/agent-playground.space -> /etc/nginx/sites-available/agent-playground.space`.
- If service restart is immediately followed by `curl` too quickly, first local health check may briefly fail. Retry loop is expected.
