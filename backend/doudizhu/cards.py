"""Card representation for Dou Dizhu.

A card is encoded as a string ``<RANK><SUIT>``.

- RANK in ``3 4 5 6 7 8 9 T J Q K A 2``
- SUIT in ``S H D C`` (Spade Heart Diamond Club)
- Jokers: ``RJ`` (small / red joker), ``BJ`` (big / black joker)

Internally each card has an integer ``rank_value`` for ordering:

    3=0, 4=1, 5=2, 6=3, 7=4, 8=5, 9=6, T=7, J=8, Q=9, K=10, A=11, 2=12,
    RJ=13, BJ=14
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

RANK_CHARS = "34567891JQKA2"  # placeholder; not used directly
RANK_ORDER = ["3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A", "2"]
SUITS = ("S", "H", "D", "C")

RANK_TO_VALUE = {r: i for i, r in enumerate(RANK_ORDER)}
RANK_TO_VALUE["RJ"] = 13
RANK_TO_VALUE["BJ"] = 14

VALUE_TO_RANK = {v: r for r, v in RANK_TO_VALUE.items()}


@dataclass(frozen=True)
class Card:
    code: str  # canonical string code, e.g. '3S', 'TC', 'BJ'

    @property
    def rank(self) -> str:
        if self.code in ("RJ", "BJ"):
            return self.code
        return self.code[0]

    @property
    def suit(self) -> str:
        if self.code in ("RJ", "BJ"):
            return ""
        return self.code[1]

    @property
    def rank_value(self) -> int:
        return RANK_TO_VALUE[self.rank]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.code


def parse_card(s: str) -> Card:
    s = s.strip().upper()
    if s in ("RJ", "BJ"):
        return Card(s)
    if len(s) != 2:
        raise ValueError(f"invalid card code: {s!r}")
    rank, suit = s[0], s[1]
    if rank not in RANK_TO_VALUE or rank in ("RJ", "BJ"):
        raise ValueError(f"invalid card rank: {s!r}")
    if suit not in SUITS:
        raise ValueError(f"invalid card suit: {s!r}")
    return Card(rank + suit)


def parse_cards(items: Iterable[str]) -> List[Card]:
    return [parse_card(s) for s in items]


def build_deck() -> List[Card]:
    deck: List[Card] = []
    for rank in RANK_ORDER:
        for suit in SUITS:
            deck.append(Card(rank + suit))
    deck.append(Card("RJ"))
    deck.append(Card("BJ"))
    return deck


def sort_cards(cards: Iterable[Card]) -> List[Card]:
    """Sort cards ascending by rank_value, suit as tiebreaker."""
    return sorted(cards, key=lambda c: (c.rank_value, c.suit))
