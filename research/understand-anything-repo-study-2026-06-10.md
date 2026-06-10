# Understand-Anything repo study — 2026-06-10

Repo: <https://github.com/Egonex-AI/Understand-Anything>  
Purpose: learn product/design/agent-skill patterns useful for `ai-agent-playground`.

## What it is

Understand Anything is positioned as a multi-platform agent plugin that turns a codebase, docs, or knowledge base into an interactive knowledge graph. It supports Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, OpenClaw, etc. Core flows advertised in README:

- `/understand`: scan/analyze codebase and save `.understand-anything/knowledge-graph.json`.
- `/understand-dashboard`: launch a token-gated interactive graph dashboard.
- `/understand-chat`: ask questions about the generated graph.
- `/understand-diff`: impact analysis for current changes.
- `/understand-explain`: explain a specific file/function.
- `/understand-onboard`: generate onboarding guide.
- `/understand-domain`: extract business-domain flows.
- `/understand-knowledge`: analyze wiki/knowledge-base graphs.

## Architecture patterns observed

### 1. Skill-as-product surface

The repo is not just a library; it packages workflows as named agent skills/commands. Each skill has:

- a clear command name and argument hint;
- deterministic preflight steps;
- explicit generated artifacts under `.understand-anything/`;
- fallback/root resolution rules across platforms;
- validation/error-handling instructions.

Useful for agent-playground: expose agent-facing workflows as explicit handles/docs, not only UI buttons. For example, future skills could be:

- `playground-smoke`: create/join/play one synthetic game and verify action contracts.
- `playground-deploy`: self-check, commit, push, deploy, verify public commit.
- `playground-analyze-game`: summarize a room/game transcript/event log for agents.

### 2. Graph + dashboard separation

Understand Anything stores graph JSON as the durable artifact, then the dashboard is just a visualizer over that artifact. This clean split is strong:

- analysis is expensive and persistent;
- dashboard is restartable and read-only;
- teams can commit/share the graph;
- agents can read the same JSON humans see.

Useful for agent-playground: game state/action history could eventually be exportable as a durable JSON event graph, separate from live UI. That would support replay, agent evaluation, debugging, and onboarding.

### 3. Multi-stage pipeline

The project decomposes understanding into deterministic preprocessing + LLM/agent analysis + validation + dashboard. Domain skill documentation shows phases:

1. resolve project root/plugin root;
2. detect existing graph;
3. lightweight scan or derive from existing graph;
4. dispatch analyzer agent;
5. validate/save graph;
6. launch dashboard.

Useful for agent-playground: avoid monolithic “agent decides everything” loops. Keep deterministic extraction/state/action schemas first, then let agents reason over compact, validated context.

### 4. Incremental/staleness mindset

README emphasizes re-run incremental analysis, diff impact, auto-update on commit, and graph sharing. The core package has tests around staleness/fingerprint/change classifier. This is operationally mature: expensive analysis should be cacheable and invalidated by fingerprints.

Useful for agent-playground:

- use health/version commit already added as deploy fingerprint;
- add future room/game replay hash or event-log sequence number;
- add action schema version to `/action-schema`;
- use smoke tests as deployment gates.

### 5. Multi-platform install and distribution

The repo includes plugin descriptors for Claude/Cursor/Copilot/OpenCode/etc. It has one-line installer, marketplace docs, localized READMEs, and a homepage. This is product/ops thinking, not just code.

Useful for agent-playground website operations:

- docs should show “agent quick start” in multiple platform contexts;
- public docs should include copy-paste curl flows;
- landing page should show live demo/health/API docs visibly;
- version/commit public health makes support easier.

## Web/product design lessons

### Landing page

README/homepage position the product with:

- crisp headline: “Turn any codebase… into an interactive knowledge graph”;
- immediate pain: “200,000 lines of code, where do you start?”;
- feature cards grouped by user value;
- live demo CTA;
- compatibility badges;
- multilingual documentation.

Useful for agent-playground:

- current site should present a stronger value prop than “game playground”: “HTTP-native multi-agent game arena with machine-readable UI/action handles”.
- add CTA cards: Play in browser / Connect an agent / Read API docs / View live health.
- add screenshots/GIFs for Texas oval table and Dou Dizhu table once stable.
- make “no DOM scraping — use `/ui-state` + `/action`” a visible principle.

### Dashboard patterns

Dashboard token-gates graph data and separates data directory via env (`GRAPH_DIR`). Useful pattern for agent-playground admin/debug dashboards:

- token-gated room replay viewer;
- read-only action/event log explorer;
- hidden admin diagnostics using explicit token rather than relying on obscurity.

## Agent API lessons for `ai-agent-playground`

Understand-Anything repeatedly turns messy workspace information into a compact artifact agents can consume. Agent-playground is already moving the same way with `/ui-state`, `/actions`, `/action-schema`, and `/action`.

Concrete next steps inspired by this repo:

1. Add `schema_version` to `/ui-state` and `/action-schema`.
2. Add `event_log` to game UI state so agents can reason without scraping visual history.
3. Add replay/export endpoint: `GET /api/games/{id}/events` or `/replay`.
4. Add deploy/version visibility already started via `/api/health`; continue with action schema version.
5. Add a public “Agent quick start” landing page section mirroring Understand-Anything’s concise install/run flow.
6. Build a small agent-onboarding guide: “create key → create room → join → loop over `/ui-state` → execute `/action`”.

## Risks / caveats from repo study

- Clone/checkout can be heavy and brittle; repo has many tree-sitter dependencies/assets. For our own docs/skills, keep research notes compact and avoid requiring huge checkout for routine heartbeats.
- Complex multi-platform support needs rigorous tests. If agent-playground adds official SDK/plugins, add smoke tests per public contract first.
- Dashboard token/access model is important; if we add replay/admin dashboards, do not expose private hands or tokens casually.

## Recommended immediate agent-playground backlog additions

- Add `schema_version` to `/ui-state` and `/action-schema`.
- Add `event_log` field normalized across Dou Dizhu/Texas.
- Create a homepage “For Agents” section with curl loop and health/version badge.
- Create `scripts/verify_deploy_health.py` style scripts for `/ui-state` and `/action-schema` public contract once a demo room fixture exists.
- Consider a future `.agent-playground/` export artifact for completed games, analogous to `.understand-anything/knowledge-graph.json`.
