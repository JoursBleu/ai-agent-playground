# Backend game interface notes

`backend/game_interface.py` is the source of truth for stable, machine-facing game contracts. Keep HTTP routing thin: routes should find the room, enforce auth/settlement, then delegate shared schema/view construction to this module.

## Current boundary

`backend/game_interface.py` owns:

- `GameInterface`: stable metadata for one game type.
- `INTERFACES` / `interface_names()`: supported game-type registry used by `/api/capabilities`.
- `GameInterface.action_schema()`: stable action list for `/action-schema.actions`.
- `GameInterface.action_schema_response(...)`: full `/api/games/{game_id}/action-schema` response.
- `GameInterface.action_descriptors(...)`: current visible action handles for `/actions` and `/ui-state.actions`.
- `GameInterface.apply_action(...)`: normalized game mutation dispatch used by unified `POST /action`.
- `event_log_for(game_type, state)`: normalized `event_log` / `/events` representation.
- `base_ui_state(...)`: common `/ui-state` fields shared by all games.
- `table_view_for(game_type, state, event_log)`: per-game `/ui-state.table` fields.

`backend/game_routes.py` should own:

- FastAPI paths, request/response models, and auth dependencies.
- Room lookup and lifecycle side effects (`maybe_settle`, leave/disband/restart, chat).
- HTTP error translation around interface/engine exceptions.

## Rules for future changes

1. Do not hand-write a new game's action schema inside `game_routes.py`.
   - Add a new `GameInterface` entry instead.
2. If a field is visible in browser UI and should be agent-readable, expose it through `base_ui_state(...)` or `table_view_for(...)`.
3. If a new history/action event appears, normalize it through `event_log_for(...)` so `/ui-state.event_log` and `/events` stay identical.
4. Keep `/actions` for current enabled handles and `/action-schema` for stable operation contracts.
5. Route-level compatibility endpoints may remain, but new UI/agent paths should use `/ui-state`, `/actions`, `/action-schema`, `/events`, and unified `POST /action`.

## Next extraction targets

`action_descriptors(...)` and unified `apply_generic_action(...)` now delegate through `GameInterface`. Next useful seams:

- Rename the current metadata-centric `GameInterface` into a clearer adapter shape, or introduce a separate adapter object if the module grows.
- Move game-type-specific exception translation closer to the interface so routes do not need to import every engine error class.
- Add a new-game checklist that starts from a `GameInterface` entry before touching routes.

Possible longer-term adapter shape:

```python
class GameAdapter(Protocol):
    game_type: str
    def legal_actions(self, state: dict, token: str | None) -> list[dict]: ...
    def apply_action(self, game, req) -> dict: ...
```

The near-term goal is not a large rewrite; keep migrating one verifiable seam at a time.
