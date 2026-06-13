# Observable action handles for human UI + agent API

Date: 2026-06-13

## Why this matters

AgentPlayground now has two consumers for the same game surface:

- humans clicking browser controls;
- agents reading JSON and executing HTTP actions.

If the browser UI invents its own action semantics, agents drift out of sync. If agents must scrape text or infer button meaning from layout, automation becomes brittle. The durable pattern is: every human-visible action should have a stable machine-readable handle, and every handle should map to the same backend operation contract agents call.

## Comparable patterns worth borrowing

### Playwright-style locator contracts

Playwright tests work best when UI exposes stable selectors such as `data-testid`, roles, accessible labels, and deterministic disabled states. The lesson for AgentPlayground is not to make agents scrape visual text; instead, expose action identity directly on controls:

- `data-action-id="raise"`
- `data-action-enabled="true|false"`
- `data-disabled-reason="not your action window"`

This gives browser automation a stable locator while still letting designers change labels, layout, language, or CSS.

### RL / Gym action spaces

Reinforcement-learning environments separate observation from action space. The useful adaptation for card-game web UIs is:

- `/ui-state` is the observation;
- `actions[]` is the current action space;
- `POST /action` is the transition function;
- `event_log` is the normalized trace for replay/debug.

This makes the game feel like an HTTP-native environment while preserving a normal human UI.

### OpenAI / tool-calling schemas

Tool-calling APIs publish action names and parameter schemas before the model acts. For AgentPlayground, `/action-schema` should remain the stable operation catalogue, while `/actions` and `/ui-state.actions` are the current enabled handles with concrete params/ranges. Keep these distinct:

- schema = what operations exist;
- actions = what is legal now;
- action result = state transition + normalized result.

### DOM as an inspectable projection, not source of truth

The DOM should not be the authoritative game state. It should be a projection of `/ui-state`. But once projected, it should preserve enough machine metadata for browser agents to verify they are clicking the same handle the HTTP API would call.

That means DOM action attributes are verification and automation affordances, not a replacement for `/ui-state`.

## Recommended contract for AgentPlayground

For every interactive game control that executes `POST /api/games/{game_id}/action`:

1. Source its enabled/disabled state from `/ui-state.actions` where possible.
2. Include stable DOM metadata:
   - `data-action-id`
   - `data-action-enabled`
   - `data-disabled-reason`
3. If the action has concrete params/ranges, expose them either in nearby machine-readable text or dedicated data attrs where useful:
   - `data-action-min`
   - `data-action-max`
   - `data-action-amount`
4. Route clicks through the shared `gameAction(action, payload)` helper.
5. Keep deployed verification in place so CDN/static deploy drift is caught:
   - local smoke: `scripts/smoke_unified_frontend_actions.py`
   - public static check: `scripts/verify_public_frontend_actions.py`
   - full suite: `scripts/verify_public_deploy.py`

## Anti-patterns to avoid

- Button text is the only action identifier.
- Human UI calls `/bid`, `/play`, `/texas/action`, while agents call `/action`.
- Disabled state is recomputed separately in JS and diverges from `/ui-state.actions`.
- `/ui-state` exposes information that is not visible to the user, or the UI shows information omitted from `/ui-state`.
- Public deploy verification only checks API JSON and misses stale static JS.

## Next concrete improvements

1. Add optional `data-action-param-*` attrs for Texas raise min/max and call amount.
2. Add a tiny browser/DOM smoke that mounts mocked action arrays and asserts rendered buttons contain the expected data attributes.
3. Keep moving remaining UI-specific legality checks toward `actions[]` so buttons are a projection of the same handle list agents consume.
4. Consider documenting `data-action-*` as a supported browser-agent surface in `docs/AGENT_API.md`.
