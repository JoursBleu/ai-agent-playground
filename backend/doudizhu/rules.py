"""Dou Dizhu rule engine.

The rule engine has two responsibilities:

1. **Pattern recognition** — given a list of cards, identify what hand pattern
   (single / pair / trio / straight / bomb / rocket / ...) they form, or reject
   them as illegal.
2. **Comparison** — given two patterns, decide whether the second one beats
   the first (only same-category & same-length plays beat each other, with the
   exception of bombs / rocket).

The engine is intentionally pluggable so that we can swap out the built-in
hard-coded rules for an external **referee** (e.g. an LLM agent that judges
plays).  Each ``Game`` instance holds one ``RuleEngine`` instance, chosen at
creation time.

Built-in patterns supported
---------------------------
- single (1)
- pair (2)
- trio (3)
- trio + single (4)
- trio + pair (5)
- straight: 5+ consecutive singles, no 2 / jokers, rank 3..A
- pair-straight (连对): 3+ consecutive pairs, no 2 / jokers
- airplane (飞机): 2+ consecutive trios, no 2 / jokers
- airplane + singles (一对应一组)
- airplane + pairs
- four + two singles
- four + two pairs
- bomb (4 of a kind)
- rocket (RJ + BJ)
"""

from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from .cards import Card, RANK_TO_VALUE


class HandCategory(str, enum.Enum):
    SINGLE = "single"
    PAIR = "pair"
    TRIO = "trio"
    TRIO_SINGLE = "trio_single"
    TRIO_PAIR = "trio_pair"
    STRAIGHT = "straight"
    PAIR_STRAIGHT = "pair_straight"
    AIRPLANE = "airplane"
    AIRPLANE_SINGLE = "airplane_single"
    AIRPLANE_PAIR = "airplane_pair"
    FOUR_TWO_SINGLE = "four_two_single"
    FOUR_TWO_PAIR = "four_two_pair"
    BOMB = "bomb"
    ROCKET = "rocket"


@dataclass(frozen=True)
class HandPattern:
    category: HandCategory
    main_value: int  # value used for comparison within the same category
    length: int      # number of "groups" (e.g. straight length, # of trios)
    cards: tuple     # original played cards (as Card tuple)

    def as_dict(self) -> dict:
        return {
            "category": self.category.value,
            "main_value": self.main_value,
            "length": self.length,
            "cards": [c.code for c in self.cards],
        }


# ---------------------------------------------------------------------------
# Engine interface
# ---------------------------------------------------------------------------


class RuleEngine:
    """Pluggable rule engine interface."""

    name: str = "base"

    def identify(self, cards: Sequence[Card]) -> Optional[HandPattern]:
        """Return the ``HandPattern`` for *cards*, or ``None`` if illegal."""
        raise NotImplementedError

    def beats(self, prev: HandPattern, curr: HandPattern) -> bool:
        """Return True if ``curr`` legally beats ``prev`` on the table."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Built-in engine
# ---------------------------------------------------------------------------


def _counts_by_value(cards: Sequence[Card]) -> Counter:
    return Counter(c.rank_value for c in cards)


def _is_consecutive(values: Sequence[int], length: int, max_value: int = 11) -> bool:
    """values must already be sorted ascending, unique.

    A straight in Dou Dizhu cannot contain 2 (value 12) or jokers (13/14).
    ``max_value=11`` corresponds to A.
    """
    if len(values) != length:
        return False
    if values[-1] > max_value:
        return False
    return all(values[i + 1] - values[i] == 1 for i in range(len(values) - 1))


class BuiltinRuleEngine(RuleEngine):
    name = "builtin"

    # ---- identification -------------------------------------------------

    def identify(self, cards: Sequence[Card]) -> Optional[HandPattern]:
        cards = list(cards)
        n = len(cards)
        if n == 0:
            return None
        counts = _counts_by_value(cards)
        values_sorted = sorted(counts.keys())
        sig = tuple(sorted(counts.values(), reverse=True))

        # Rocket: RJ + BJ
        if n == 2 and set(c.code for c in cards) == {"RJ", "BJ"}:
            return HandPattern(HandCategory.ROCKET, 100, 1, tuple(cards))

        # Bomb
        if n == 4 and sig == (4,):
            v = values_sorted[0]
            return HandPattern(HandCategory.BOMB, v, 1, tuple(cards))

        # Single
        if n == 1:
            return HandPattern(HandCategory.SINGLE, cards[0].rank_value, 1, tuple(cards))

        # Pair
        if n == 2 and sig == (2,):
            return HandPattern(HandCategory.PAIR, values_sorted[0], 1, tuple(cards))

        # Trio
        if n == 3 and sig == (3,):
            return HandPattern(HandCategory.TRIO, values_sorted[0], 1, tuple(cards))

        # Trio + single
        if n == 4 and sig == (3, 1):
            trio_v = max(counts, key=lambda v: (counts[v], v)) if False else next(v for v, c in counts.items() if c == 3)
            return HandPattern(HandCategory.TRIO_SINGLE, trio_v, 1, tuple(cards))

        # Trio + pair
        if n == 5 and sig == (3, 2):
            trio_v = next(v for v, c in counts.items() if c == 3)
            return HandPattern(HandCategory.TRIO_PAIR, trio_v, 1, tuple(cards))

        # Straight (5+ singles, consecutive, no 2/jokers)
        if n >= 5 and all(c == 1 for c in counts.values()) and _is_consecutive(values_sorted, n):
            return HandPattern(HandCategory.STRAIGHT, values_sorted[0], n, tuple(cards))

        # Pair-straight (连对): 3+ consecutive pairs
        if n >= 6 and n % 2 == 0 and all(c == 2 for c in counts.values()):
            uniq = sorted(counts.keys())
            if _is_consecutive(uniq, n // 2):
                return HandPattern(HandCategory.PAIR_STRAIGHT, uniq[0], n // 2, tuple(cards))

        # Airplane families: trio-runs of length k (k >= 2)
        # pure airplane
        if n >= 6 and n % 3 == 0 and all(c == 3 for c in counts.values()):
            uniq = sorted(counts.keys())
            if _is_consecutive(uniq, n // 3):
                return HandPattern(HandCategory.AIRPLANE, uniq[0], n // 3, tuple(cards))

        # airplane + singles  (k trios + k singles, total = 4k, k>=2)
        if n >= 8 and n % 4 == 0:
            k = n // 4
            trios = sorted(v for v, c in counts.items() if c == 3)
            # remaining cards as 1's (or 2's that we don't fully use)
            # Allow extras to be of count 1 or part of pair (we only need k singles total,
            # any pair would be ambiguous → reject to keep rules simple).
            if len(trios) == k and _is_consecutive(trios, k):
                # check the rest are "k loose cards", not a pair set
                others = [v for v, c in counts.items() if c != 3]
                others_total = sum(counts[v] for v in others)
                if others_total == k and all(counts[v] in (1, 2) for v in others):
                    # also forbid trios in extras (already excluded) and forbid using a 4-of-a-kind as trio
                    return HandPattern(HandCategory.AIRPLANE_SINGLE, trios[0], k, tuple(cards))

        # airplane + pairs  (k trios + k pairs, total = 5k, k>=2)
        if n >= 10 and n % 5 == 0:
            k = n // 5
            trios = sorted(v for v, c in counts.items() if c == 3)
            pairs = sorted(v for v, c in counts.items() if c == 2)
            if (
                len(trios) == k
                and len(pairs) == k
                and _is_consecutive(trios, k)
                and len(counts) == 2 * k
            ):
                return HandPattern(HandCategory.AIRPLANE_PAIR, trios[0], k, tuple(cards))

        # Four + two singles
        if n == 6 and sig == (4, 1, 1):
            v = next(v for v, c in counts.items() if c == 4)
            return HandPattern(HandCategory.FOUR_TWO_SINGLE, v, 1, tuple(cards))

        # Four + two pairs
        if n == 8 and sig == (4, 2, 2):
            v = next(v for v, c in counts.items() if c == 4)
            return HandPattern(HandCategory.FOUR_TWO_PAIR, v, 1, tuple(cards))

        return None

    # ---- comparison -----------------------------------------------------

    def beats(self, prev: HandPattern, curr: HandPattern) -> bool:
        # Rocket beats everything.
        if curr.category == HandCategory.ROCKET:
            return True
        if prev.category == HandCategory.ROCKET:
            return False
        # Bomb beats anything non-bomb / non-rocket.
        if curr.category == HandCategory.BOMB and prev.category != HandCategory.BOMB:
            return True
        if prev.category == HandCategory.BOMB and curr.category != HandCategory.BOMB:
            return False
        # Same category & same length → compare main value.
        if curr.category != prev.category:
            return False
        if curr.length != prev.length:
            return False
        return curr.main_value > prev.main_value


# ---------------------------------------------------------------------------
# Referee engine — delegates decisions to an external HTTP agent
# ---------------------------------------------------------------------------


class RefereeRuleEngine(RuleEngine):
    """Delegates rule decisions to an external HTTP "referee" agent.

    The referee must expose two endpoints (all JSON):

    - ``POST {url}/identify``
        body: ``{"cards": ["3S", "3H", ...]}``
        resp: ``{"legal": true, "category": "pair", "main_value": 0,
                 "length": 1}``  (or ``{"legal": false}``)

    - ``POST {url}/beats``
        body: ``{"prev": <pattern dict>, "curr": <pattern dict>}``
        resp: ``{"beats": true}``

    If the referee is unreachable, the engine falls back to
    ``BuiltinRuleEngine`` (so games never get stuck).
    """

    name = "referee"

    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._fallback = BuiltinRuleEngine()

    def _post(self, path: str, payload: dict) -> Optional[dict]:
        try:
            import urllib.request
            import json

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.url}{path}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def identify(self, cards: Sequence[Card]) -> Optional[HandPattern]:
        result = self._post("/identify", {"cards": [c.code for c in cards]})
        if result is None:
            return self._fallback.identify(cards)
        if not result.get("legal"):
            return None
        try:
            return HandPattern(
                category=HandCategory(result["category"]),
                main_value=int(result["main_value"]),
                length=int(result.get("length", 1)),
                cards=tuple(cards),
            )
        except (KeyError, ValueError):
            return None

    def beats(self, prev: HandPattern, curr: HandPattern) -> bool:
        result = self._post(
            "/beats",
            {"prev": prev.as_dict(), "curr": curr.as_dict()},
        )
        if result is None:
            return self._fallback.beats(prev, curr)
        return bool(result.get("beats", False))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_rule_engine(mode: str = "builtin", referee_url: Optional[str] = None) -> RuleEngine:
    """Return a rule engine instance.

    Args:
        mode: ``"builtin"`` (default) or ``"referee"``.
        referee_url: required when mode == ``"referee"``.
    """
    mode = (mode or "builtin").lower()
    if mode == "builtin":
        return BuiltinRuleEngine()
    if mode == "referee":
        if not referee_url:
            raise ValueError("referee mode requires referee_url")
        return RefereeRuleEngine(referee_url)
    raise ValueError(f"unknown rule mode: {mode!r}")
