# Refactor Notes

Date: 2026-06-08

## Goal

Move ai-agent-playground away from a giant all-in-one FastAPI + single-file frontend toward a maintainable structure that can support a full UI/game rewrite.

## Backend split

Old:

- `backend/main.py` contained app bootstrap, room registry, background workers, settlement, all game API routes, and static serving.

New:

- `backend/main.py` — app bootstrap, router registration, static frontend, `/docs-agent`.
- `backend/game_routes.py` — public game/admin game API routes. URLs are unchanged.
- `backend/game_state.py` — in-memory room registry, user-room mapping, room reaper.
- `backend/settlement.py` — point settlement after finished rounds.
- `backend/background.py` — background worker startup: idle reaper, deposit expiry loop, BSC scanner.

## Frontend split

Old:

- `backend/static/index.html` was a 3392-line single file containing HTML, CSS, i18n text, and all JS logic.

New:

- `backend/static/index.html` — DOM markup only.
- `backend/static/css/app.css` — extracted styles.
- `backend/static/js/i18n.js` — zh/en text pack and i18n helpers.
- `backend/static/js/core.js` — global runtime state, DOM helper, modal helpers, API helper, log, escaping.
- `backend/static/js/auth-ui.js` — auth/account/admin/API key/recharge/points UI.
- `backend/static/js/app.js` — lobby, room navigation, polling, clock, shared room chat.
- `backend/static/js/doudizhu-ui.js` — Dou Dizhu board renderer.
- `backend/static/js/zhajinhua-ui.js` — Zhajinhua board renderer.
- `backend/static/js/texas-ui.js` — Texas Hold'em board renderer/actions.
- `backend/static/js/social-ui.js` — AI Social chat/blog modal UI.

## Compatibility kept

- Existing game API paths are unchanged.
- Existing static DOM ids are unchanged.
- Existing global function names used by inline-generated HTML are preserved for now.

## Validation run

- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`
- Static asset/path checks for all extracted JS/CSS files.
- Checked key functions exist after split:
  - `render()` in `doudizhu-ui.js`
  - `renderZjh()` in `zhajinhua-ui.js`
  - `renderTexas()` in `texas-ui.js`
  - `refresh()` in `app.js`
  - `api()` in `core.js`
  - `loadMe()` in `auth-ui.js`
  - `openAiChat()` in `social-ui.js`

## Next rewrite steps

1. Replace global mutable frontend variables with a single `AAP` namespace or ES modules.
2. Move inline-generated `onclick="..."` HTML to delegated event handlers.
3. Redesign Texas/Dou Dizhu UI around reusable components:
   - `renderSeat`
   - `renderCard`
   - `renderActionBar`
   - `renderActionLog`
4. Add backend game interface/adapters:
   - `public_state`
   - `private_state`
   - `post_chat`
   - `chat_since`
   - `is_owner`
   - `disband`
   - `restart`
   - `compute_settlement`
5. Later: turn each game engine into `GameState + Action + legalActions + applyAction + event log`.


## 2026-06-09 iteration: unified frontend game actions

Frontend game operation buttons now use the generic agent handle:

- Dou Dizhu bid -> `POST /api/games/{game_id}/action` with `{action:"bid", bid}`
- Dou Dizhu play -> `{action:"play_cards", cards}`
- Dou Dizhu pass -> `{action:"pass"}`
- Texas actions -> `{action:"fold|check|call|raise|all_in"}`

The legacy endpoints remain on the backend for compatibility, but the browser UI now exercises the same action surface that agents should call. This reduces semantic drift between human UI and agent integration.

Validation:

- `node --check backend/static/js/*.js`
- `python3 -m compileall -q backend`
- Static grep confirms frontend no longer calls `/bid`, `/play`, or `/texas/action` directly.


## 2026-06-09 heartbeat workflow update

User explicitly asked that heartbeat work should not only run server checks; it should continuously iterate on agent-playground while also learning related skills and researching comparable open-source projects.

`/home/node/.openclaw/workspace/HEARTBEAT.md` now includes an agent-playground-first section. Future heartbeats should pick one small verifiable step, such as:

- migrate frontend rendering from legacy `/state` toward `/ui-state`;
- keep human UI actions and agent API actions unified on `/api/games/{game_id}/action`;
- improve Texas/Dou Dizhu table UI;
- extract a backend game interface (`GameState + Action + legalActions + applyAction + event log`);
- research open-source card/game/agent playground projects and write notes.

Validation after this note:

- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: dependency-free agent API smoke test

Added `scripts/smoke_agent_api_contract.py` to validate agent-facing game contracts without needing FastAPI/pydantic/bcrypt installed locally. It stubs web/auth dependencies, constructs real Dou Dizhu and Texas games, and checks:

- `ui_state(...)` includes machine-readable `table`, `seats`, `clock`, `actions`;
- `action_descriptors(...)` exposes expected action ids;
- `apply_generic_action(...)` dispatches through the same generic `/action` contract used by agents and the browser UI.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Texas renderer ui-state compatibility

Moved `texas-ui.js` toward the machine-readable `/ui-state` shape by introducing and using compatibility helpers from `core.js`:

- `gameTable()` / `gameSeats()` / `gameClock()`
- `gameCommunity()` / `gameHistory()`
- `gameRoundNo()` / `gamePot()` / `gameCurrentBet()` / `gameStreet()` / `gameCurrentTurn()`

Texas rendering now accepts either legacy flat `/state` or the newer `/ui-state` layout for table, seats, clock, community cards, history, pot/current bet, street, dealer/current turn, and showdown.

Validation run:

- `node --check backend/static/js/texas-ui.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: refresh prefers `/ui-state`

Moved the main frontend refresh path from legacy `/state`-first to `/ui-state`-first:

- added `fetchLegacyState()` only as compatibility fallback;
- `refresh()` now calls `fetchUiState()` first, normalizes it via `normalizeUiStateForLegacyRender(...)`, and renders the main UI from that shape;
- the Agent Handle panel receives the exact raw `/ui-state` response;
- legacy `/state` remains a fallback when `/ui-state` fails;
- spectator chat fetch is now only a fallback when the state shape lacks chat.

Added `normalizeUiStateForLegacyRender(...)` in `core.js` so older renderers can gradually migrate while the main data source is already agent-readable.

Validation run:

- `node --check backend/static/js/core.js`
- `node --check backend/static/js/app.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Texas oval table UI

Reworked the Texas Hold'em board from a flat seat list into a casino-style oval table:

- added `.texas-table-oval` felt table with center community-card area;
- seats now render around the oval using computed positions;
- each seat displays name, chips, current bet, acting/dealer/you badges, and mini hole-card tiles;
- pot/current bet are mirrored into the center of the table;
- added an `Agent Actions` mirror panel showing the same `actions` list agents consume from `/ui-state`;
- kept old action buttons intact, now backed by the generic `/action` helper.

Validation run:

- `node --check backend/static/js/texas-ui.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Texas poker action bar backed by `/ui-state` actions

Reworked the Texas action controls into a poker-style bottom action bar:

- fold/check/call/raise/all-in buttons now use `/ui-state` `actions[]` enabled/disabled state instead of duplicating turn logic in the renderer;
- disabled buttons expose `disabled_reason` as title text;
- call button mirrors current call amount;
- raise is now a range slider plus numeric input, synchronized both ways;
- raise min/max are read from the `raise` action params when available, falling back to `me.min_raise_to` / `me.max_raise_to`;
- the action mirror remains visible so human UI and agent handles can be compared directly.

Validation run:

- `node --check backend/static/js/texas-ui.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Dou Dizhu three-player table UI

Started the Dou Dizhu board rewrite into a clearer three-player table:

- replaced the old stacked bottom/table/hand layout with a felt table containing left/top/right player positions;
- added table-center zones for bottom cards and the current trick / last plays;
- added per-seat cards showing name, role, hand count, landlord/acting/you badges;
- moved the hand into a dedicated bottom hand panel;
- added selection count feedback plus `提示` / `重选` controls;
- kept the existing generic `/action` calls for bid/play/pass.

Validation run:

- `node --check backend/static/js/doudizhu-ui.js`
- `node --check backend/static/js/app.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Dou Dizhu local legal hint

Upgraded the Dou Dizhu `提示` button from a placeholder "select first card" action into a local rules-aware hint helper:

- recognizes common Dou Dizhu patterns in the browser: single, pair, triple, triple+single, triple+pair, straight, consecutive pairs, airplane, bomb, rocket;
- compares candidate plays against the current `last_play_cards` from `/ui-state` / normalized state;
- avoids spending bombs/rocket when a non-bomb response exists;
- selection feedback now shows both selected count and recognized pattern category;
- keeps the actual authoritative legality check on the backend when `/action` submits `play_cards`.

This is still a UI assistant, not a referee replacement. Backend remains source of truth.

Validation run:

- `node --check backend/static/js/doudizhu-ui.js`
- `node --check backend/static/js/app.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: backend Dou Dizhu hint action

Moved Dou Dizhu hinting into the agent-readable backend contract:

- added `backend/doudizhu/hints.py` with `find_legal_hint(...)`;
- hint helper uses the builtin rule engine to identify candidate combinations and compare them against `last_play_cards`;
- `/ui-state` / `actions` now exposes `play_hint` with `cards`, `pattern`, and `hint_reason` params when a suggestion exists;
- replaced the previous `play_smallest_single` handle with a more useful legal hint handle;
- smoke test now asserts that playing-state Dou Dizhu actions include an enabled `play_hint` with cards and pattern.

The hint remains advisory; submitted `play_cards` is still validated by the backend game engine.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Dou Dizhu UI consumes backend `play_hint`

Aligned the human Dou Dizhu hint button with the agent-readable backend contract:

- frontend `findDdzHint()` now prefers `/ui-state` / `actions[]` `play_hint` params;
- local browser hinting remains as a fallback only when backend hint is absent;
- hint logging shows backend/local source and pattern category;
- disabled backend hints report `disabled_reason` instead of selecting cards outside the action window.

This keeps human UI and agent handles using the same recommended action whenever the backend provides one.

Validation run:

- `node --check backend/static/js/doudizhu-ui.js`
- `node --check backend/static/js/app.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Agent API docs for `play_hint`

Updated `docs/AGENT_API.md` to reflect the current agent-facing contract:

- `/ui-state` example now includes `play_hint`;
- removed stale `play_smallest_single` execution example;
- documented that `play_hint` is an advisory action handle whose `params.cards` should be submitted through canonical `play_cards`;
- added a recommended agent decision loop: read `/ui-state`, inspect enabled `actions[]`, execute through `/action`, continue from returned `ui_state`;
- reiterated the no-DOM-scraping principle.

Validation run after doc edit:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: action schema alignment

Aligned backend action metadata with the current `/ui-state` actions contract:

- Texas `raise` action params now expose both `min`/`max` and legacy `min_amount`/`max_amount` keys;
- `/action-schema` now documents `play_hint` instead of stale `play_smallest_single`;
- schema marks `play_hint` as advisory and shows it should execute as canonical `play_cards` with `params.cards`;
- generic `/action` now accepts `play_hint` too, internally resolving the backend hint and dispatching through `game.play(...)` for validation.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: smoke executes `play_hint`

Strengthened the dependency-free agent API smoke test:

- after verifying Dou Dizhu `actions[]` exposes enabled `play_hint`, the smoke now calls generic `/action` dispatch via `apply_generic_action(..., action="play_hint")`;
- asserts the result is a real `play` and the player's hand count decreases;
- this catches regressions where `play_hint` appears in action metadata but cannot actually execute.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: smoke executes Texas `raise`

Strengthened the dependency-free agent API smoke test for Texas Hold'em:

- after verifying `actions[]` exposes fold/check/call/raise/all_in, the smoke now prefers executing generic `/action` `raise` with `you.min_raise_to` when available;
- falls back to check/call only when raise is unavailable;
- this catches regressions in `raise` amount handling and keeps the action metadata/schema aligned with executable behavior.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: smoke covers `/action-schema`

Extended the dependency-free smoke test to cover static action schema:

- registers smoke games in the in-memory `GAMES` map and calls `get_action_schema(...)` directly;
- asserts Dou Dizhu schema includes `play_hint` and no longer exposes stale `play_smallest_single`;
- asserts Texas `raise` schema includes `amount`, `min`, and `max` params.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: smoke covers generic `/action` route response

Moved the contract smoke one layer closer to real HTTP behavior:

- smoke now calls `generic_action(...)` route handler directly for Dou Dizhu `play_hint`;
- smoke now calls `generic_action(...)` for Texas raise/check/call execution path;
- asserts route responses include `ok: true`, executable `result`, and returned `ui_state` with `game_type`/`actions`;
- keeps dependency-free execution by using local stubs rather than starting FastAPI.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: Dou Dizhu frontend pattern names aligned

Aligned the frontend fallback Dou Dizhu hint pattern names with backend `HandCategory` values:

- `triple` -> `trio`
- `triple_single` -> `trio_single`
- `triple_pair` -> `trio_pair`
- `pairs` -> `pair_straight`

This avoids human UI hint labels drifting from `/ui-state` / backend rule-engine categories when the browser fallback is used.

Validation run:

- `node --check backend/static/js/doudizhu-ui.js`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: direct smoke tests for Dou Dizhu hint helper

Added direct smoke coverage for `backend.doudizhu.hints.find_legal_hint(...)`:

- leading a trick chooses the smallest legal single;
- responding to a pair chooses the smallest higher pair;
- rocket is suggested when it is the only available response to a high pair.

This protects the advisory hint helper independently from route/action contract tests.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: more Dou Dizhu hint edge coverage

Expanded direct smoke coverage for `find_legal_hint(...)`:

- responding to a straight chooses a legal higher straight of matching length;
- bomb is suggested as a fallback response to an otherwise unbeatable high pair;
- rocket fallback remains covered.

This further locks hint behavior for both human UI and agent-facing `play_hint`.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: removed stale `play_smallest_single` dispatcher

Removed the leftover generic `/action` dispatcher branch for the deprecated `play_smallest_single` action.  The supported advisory handle is now `play_hint`, with schema/smoke coverage ensuring the stale handle does not reappear in `/action-schema`.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: health endpoint exposes deployed version

Added lightweight deployment verification metadata to `/api/health`:

- response now includes `version.commit` and `version.source`;
- commit is read from `AAP_GIT_COMMIT` / `GIT_COMMIT` when provided, otherwise from local git checkout;
- smoke test now covers the health contract.

This makes post-deploy verification explicit: public `/api/health` can confirm which commit is live.

Validation run:

- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`

## 2026-06-10 iteration: deploy health verification script

Added `scripts/verify_deploy_health.py` for deployment closure:

- reads public `/api/health` from a configurable base URL;
- verifies `ok: true` and that `version.commit` is present;
- optionally asserts the deployed commit starts with an expected prefix;
- sends an explicit User-Agent so Cloudflare does not block Python's default urllib client.

Validation run:

- `python3 scripts/verify_deploy_health.py https://agent-playground.space ef55d45`
- `python3 scripts/smoke_agent_api_contract.py`
- `python3 -m compileall -q backend`
- `node --check backend/static/js/*.js`
