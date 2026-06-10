"""Dou Dizhu hint helpers.

These helpers are non-authoritative convenience utilities for UI/agent handles.
The server-side rule engine remains the source of truth for submitted actions.
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable, Optional

from .cards import Card, parse_cards, sort_cards
from .rules import BuiltinRuleEngine, HandPattern, HandCategory


def _pattern_sort_key(pattern: HandPattern) -> tuple:
    is_power = pattern.category in (HandCategory.BOMB, HandCategory.ROCKET)
    return (1 if is_power else 0, len(pattern.cards), pattern.main_value, pattern.category.value)


def find_legal_hint(
    hand_codes: Iterable[str],
    *,
    last_play_codes: Optional[Iterable[str]] = None,
    must_lead: bool = False,
    max_combo: int = 8,
) -> Optional[dict]:
    """Return a small legal play suggestion for a Dou Dizhu hand.

    The helper enumerates card combinations up to ``max_combo`` cards, asks the
    builtin rule engine to identify them, and returns the smallest candidate
    that either leads a trick or beats ``last_play_codes``.  Bombs/rocket are
    sorted after non-power plays when a normal answer exists.
    """

    engine = BuiltinRuleEngine()
    hand = sort_cards(parse_cards(hand_codes))
    if not hand:
        return None

    prev = None
    if not must_lead and last_play_codes:
        prev_cards = parse_cards(last_play_codes)
        prev = engine.identify(prev_cards)

    candidates: list[HandPattern] = []
    limit = min(max_combo, len(hand))
    # Most useful hints are short. Full enumeration up to 8 handles singles,
    # pairs, triples, bombs, rockets, trio attachments, and common straights.
    for n in range(1, limit + 1):
        seen: set[tuple[str, ...]] = set()
        for combo in combinations(hand, n):
            key = tuple(c.code for c in combo)
            if key in seen:
                continue
            seen.add(key)
            pattern = engine.identify(combo)
            if not pattern:
                continue
            if prev is not None and not engine.beats(prev, pattern):
                continue
            candidates.append(pattern)

    if not candidates:
        return None
    best = sorted(candidates, key=_pattern_sort_key)[0]
    return {
        "cards": [c.code for c in best.cards],
        "pattern": best.as_dict(),
        "reason": "lead smallest legal play" if prev is None else "smallest legal response",
    }
