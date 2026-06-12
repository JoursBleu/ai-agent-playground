# Agent-readable game API patterns

Date: 2026-06-11

## Why this matters

Agent Playground's core rule is: if the human UI can see it, an agent must be
able to read it from an API; if the engine can do it, an agent must be able to
call it through an API handle.  This note captures practical API patterns to use
while migrating the front end away from `/state` and toward `/ui-state`,
`/actions`, `/action-schema`, `/events`, and `POST /action`.

## Reference patterns worth copying

### 1. State + legal actions should be one coherent snapshot

Games with agents fail when state and legal actions are fetched from unrelated
sources.  The UI snapshot should include the visible table, seats, clocks,
active player, and action handles derived from the exact same engine state.

For this repo:

- `/api/games/{game_id}/ui-state` should remain the primary reader endpoint.
- `ui_state.actions[]` should be enough for a UI builder to render enabled and
  disabled controls without hard-coding game rules.
- `/api/games/{game_id}/actions` can be a slimmer polling endpoint, but it must
  match `ui_state.actions` for the same token/state.

### 2. Stable action handles beat UI labels

Agents should dispatch stable IDs like `bid`, `play_hint`, `raise`, `check`, or
`pass`, not translated button text.  Labels are allowed to change; handles are
contract.

For this repo:

- Every visible button should map to `POST /api/games/{game_id}/action`.
- Each action descriptor should expose:
  - `id`: stable machine handle
  - `label`: human label
  - `enabled`: boolean
  - `disabled_reason`: machine-readable enough to debug
  - `params`: example/default payload fields when relevant
- Do not require visible action IDs to be unique.  Some games intentionally show
  multiple choices with the same operation handle and different params, e.g.
  Doudizhu `bid` actions for `params.bid = 0/1/2/3`.  The stable uniqueness rule
  is:
  - `/action-schema.actions[].id` must be unique.
  - visible action signatures `{id, params}` must be unique.
  - every visible action `id` must appear in `/action-schema`.

### 3. Action schema should be the durable contract

`/action-schema` should describe all operations an agent might call, not just
currently enabled actions.  This lets agents plan, validate payloads, and build
forms without waiting for a specific turn.

For this repo, keep these fields stable:

- `schema_version`
- `game_type`
- `execute_endpoint`
- `state_endpoint`
- `actions_endpoint`
- `events_endpoint`
- `actions[].id`
- `actions[].params`

### 4. Event logs are for replay, debugging, and audit

An agent needs to answer: "how did this state happen?"  A separate `/events`
endpoint avoids scraping logs from prose or DOM.

For this repo:

- `/events.events` should continue to equal `/ui-state.event_log` for the same
  readable view unless a future version intentionally separates public/private
  event streams.
- Events should be append-only during a room lifecycle.
- Each meaningful action should produce an event with action type, actor/seat,
  and relevant payload summary.

### 5. Verification should cover both no-room and room-present cases

Read-only public verification is safe, but no public room means the deepest
contract checks are skipped.  The optional demo-room verifier is a good split:

- Default: no mutation, safe for every deploy.
- Opt-in: `AAP_VERIFY_CREATE_DEMO=1 AAP_VERIFY_KEY=...` creates a temporary
  waiting room and validates room endpoints.

Future improvement: add cleanup/disband for demo rooms when the verifier also
captures owner/player token safely.

## Concrete next steps for Agent Playground

1. Frontend migration:
   - Replace any remaining direct `/state` UI reads with `/ui-state`.
   - Render controls from `actions[]` instead of ad-hoc rule checks.

2. Unified game interface:
   - Introduce a backend adapter layer with methods similar to:
     - `game_type(game) -> str`
     - `read_state(game, token/spectator) -> dict`
     - `legal_actions(game, state, token) -> list[dict]`
     - `apply_action(game, action_req) -> dict`
     - `event_log(game, state) -> list[dict]`
   - Keep game-specific engines free to differ internally, but normalize API
     output at the route boundary.

3. Verifier coverage:
   - Add an optional cleanup path for created demo rooms.
   - Add a verifier assertion that `/actions.actions` equals
     `/ui-state.actions` for the same public/token view once tokened demo flow
     exists.

## Design guardrails

- Do not require agents to parse HTML or CSS classes.
- Do not encode rules only in frontend JavaScript.
- Do not expose private cards in public/spectator views unless intentionally
  using a spectator token.
- Do not treat disabled buttons as absent actions; disabled actions explain why
  a move cannot currently be called.
- Keep schema versions explicit so breaking changes are detectable.
