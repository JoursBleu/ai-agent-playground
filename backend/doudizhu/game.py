"""Dou Dizhu game state machine.

Three players, 54 cards.  17/17/17 dealt, 3 left as 底牌.  Bidding chooses
the landlord, then play proceeds counter-clockwise (next seat = (cur+1) % 3).

State machine:
    waiting -> bidding -> playing -> finished
"""

from __future__ import annotations

import enum
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .cards import Card, build_deck, parse_cards, sort_cards
from .rules import HandPattern, RuleEngine, get_rule_engine


class Phase(str, enum.Enum):
    WAITING = "waiting"
    BIDDING = "bidding"
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass
class Player:
    player_id: str
    name: str
    seat: int
    token: str
    hand: List[Card] = field(default_factory=list)
    is_landlord: bool = False


@dataclass
class TrickRecord:
    seat: int
    cards: List[str]            # card codes; [] = pass
    pattern: Optional[str]      # category name; None = pass
    timestamp: float


class GameError(Exception):
    pass


class Game:
    def __init__(
        self,
        game_id: str,
        rule_mode: str = "builtin",
        referee_url: Optional[str] = None,
        seed: Optional[int] = None,
    ):
        self.game_id = game_id
        self.rule_mode = rule_mode
        self.referee_url = referee_url
        self.engine: RuleEngine = get_rule_engine(rule_mode, referee_url)
        self.phase: Phase = Phase.WAITING

        self.players: List[Optional[Player]] = [None, None, None]
        self._token_to_seat: Dict[str, int] = {}

        self.bottom_cards: List[Card] = []
        self.bids: List[int] = [-1, -1, -1]          # -1 = not yet bid
        self.current_bid: int = 0                    # highest bid value
        self.landlord_seat: int = -1
        self.bid_turn: int = -1                      # seat whose turn to bid

        self.current_turn: int = -1
        self.last_play_seat: int = -1
        self.last_pattern: Optional[HandPattern] = None
        self.history: List[TrickRecord] = []
        self.winner_seat: int = -1

        self._rng = random.Random(seed)
        self.created_at = time.time()

    # ---- joining --------------------------------------------------------

    def add_player(self, name: str) -> Player:
        if self.phase != Phase.WAITING:
            raise GameError("game already started")
        for seat, p in enumerate(self.players):
            if p is None:
                player = Player(
                    player_id=f"p_{secrets.token_hex(4)}",
                    name=name or f"player-{seat}",
                    seat=seat,
                    token=f"tok_{secrets.token_urlsafe(12)}",
                )
                self.players[seat] = player
                self._token_to_seat[player.token] = seat
                if all(p is not None for p in self.players):
                    self._deal()
                return player
        raise GameError("game is full")

    def seat_of(self, token: str) -> int:
        if token not in self._token_to_seat:
            raise GameError("invalid token")
        return self._token_to_seat[token]

    # ---- dealing & bidding ---------------------------------------------

    def _deal(self) -> None:
        deck = build_deck()
        self._rng.shuffle(deck)
        for i in range(3):
            assert self.players[i] is not None
            self.players[i].hand = sort_cards(deck[i * 17 : (i + 1) * 17])
        self.bottom_cards = sort_cards(deck[51:54])
        self.phase = Phase.BIDDING
        self.bid_turn = self._rng.randrange(3)

    def bid(self, token: str, value: int) -> None:
        if self.phase != Phase.BIDDING:
            raise GameError("not in bidding phase")
        seat = self.seat_of(token)
        if seat != self.bid_turn:
            raise GameError("not your turn to bid")
        if value not in (0, 1, 2, 3):
            raise GameError("bid must be 0/1/2/3")
        if value != 0 and value <= self.current_bid:
            raise GameError(f"bid must be > current bid ({self.current_bid})")
        self.bids[seat] = value
        if value > self.current_bid:
            self.current_bid = value
            self.landlord_seat = seat
        # bid=3 ends bidding immediately
        if value == 3:
            self._finalize_bidding()
            return
        # advance turn
        next_seat = (seat + 1) % 3
        # full round done?
        if all(b != -1 for b in self.bids):
            self._finalize_bidding()
            return
        # if it comes back to the highest bidder with everyone else having passed
        if self.bids[next_seat] != -1 and self.current_bid > 0:
            # all others have passed
            self._finalize_bidding()
            return
        self.bid_turn = next_seat

    def _finalize_bidding(self) -> None:
        if self.current_bid == 0:
            # nobody bid; redeal
            self.bids = [-1, -1, -1]
            self.current_bid = 0
            self.landlord_seat = -1
            self._deal()
            return
        ll = self.landlord_seat
        self.players[ll].is_landlord = True
        self.players[ll].hand = sort_cards(self.players[ll].hand + self.bottom_cards)
        self.phase = Phase.PLAYING
        self.current_turn = ll
        self.last_play_seat = -1
        self.last_pattern = None

    # ---- play -----------------------------------------------------------

    def play(self, token: str, card_codes: Sequence[str]) -> dict:
        if self.phase != Phase.PLAYING:
            raise GameError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise GameError("not your turn")

        # Pass
        if len(card_codes) == 0:
            if self.last_play_seat == -1 or self.last_play_seat == seat:
                raise GameError("cannot pass: you must lead a trick")
            self.history.append(
                TrickRecord(seat=seat, cards=[], pattern=None, timestamp=time.time())
            )
            self._advance_turn()
            return {"action": "pass"}

        # Validate cards exist in hand
        cards = parse_cards(card_codes)
        hand_codes = [c.code for c in self.players[seat].hand]
        hand_pool = list(hand_codes)
        for c in cards:
            if c.code not in hand_pool:
                raise GameError(f"card {c.code} not in hand")
            hand_pool.remove(c.code)

        pattern = self.engine.identify(cards)
        if pattern is None:
            raise GameError("illegal combination")

        # If a previous play is on the table and it's not us (we didn't just
        # win the trick), the new play must beat it.
        if self.last_play_seat != -1 and self.last_play_seat != seat:
            if not self.engine.beats(self.last_pattern, pattern):
                raise GameError("does not beat previous play")

        # Apply
        new_hand = [c for c in self.players[seat].hand if c.code in hand_pool]
        # Above keeps multiplicity since hand_pool already accounts for removals.
        # But duplicate-code cards (impossible in DDZ — every code unique) so safe.
        self.players[seat].hand = sort_cards(new_hand)
        self.last_play_seat = seat
        self.last_pattern = pattern
        self.history.append(
            TrickRecord(
                seat=seat,
                cards=[c.code for c in cards],
                pattern=pattern.category.value,
                timestamp=time.time(),
            )
        )

        if not self.players[seat].hand:
            self.phase = Phase.FINISHED
            self.winner_seat = seat
            return {"action": "play", "pattern": pattern.as_dict(), "winner": seat}

        self._advance_turn()
        return {"action": "play", "pattern": pattern.as_dict()}

    def _advance_turn(self) -> None:
        nxt = (self.current_turn + 1) % 3
        # if both opponents passed, leader keeps leading (handled implicitly:
        # after 2 passes, next player == last_play_seat — they then "lead" a new trick)
        if nxt == self.last_play_seat:
            # new trick: clear table
            self.last_pattern = None
            # last_play_seat stays = leader; play() treats leading correctly
            # since seat == last_play_seat is allowed to play anything.
        self.current_turn = nxt

    # ---- introspection --------------------------------------------------

    def public_state(self) -> dict:
        return {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "rule_mode": self.rule_mode,
            "players": [
                {
                    "seat": i,
                    "name": p.name if p else None,
                    "joined": p is not None,
                    "hand_count": len(p.hand) if p else 0,
                    "is_landlord": p.is_landlord if p else False,
                }
                for i, p in enumerate(self.players)
            ],
            "bids": list(self.bids),
            "current_bid": self.current_bid,
            "landlord_seat": self.landlord_seat,
            "bid_turn": self.bid_turn,
            "current_turn": self.current_turn,
            "last_play_seat": self.last_play_seat,
            "last_play_cards": [c.code for c in self.last_pattern.cards] if self.last_pattern else [],
            "last_play_category": self.last_pattern.category.value if self.last_pattern else None,
            "history": [
                {
                    "seat": h.seat,
                    "cards": h.cards,
                    "pattern": h.pattern,
                }
                for h in self.history[-20:]
            ],
            "winner_seat": self.winner_seat,
            # bottom is hidden during bidding, revealed once a landlord is chosen
            "bottom_cards": (
                [c.code for c in self.bottom_cards]
                if self.phase in (Phase.PLAYING, Phase.FINISHED)
                else []
            ),
        }

    def private_state(self, token: str) -> dict:
        seat = self.seat_of(token)
        state = self.public_state()
        state["you"] = {
            "seat": seat,
            "name": self.players[seat].name,
            "hand": [c.code for c in self.players[seat].hand],
            "is_landlord": self.players[seat].is_landlord,
            "is_your_turn": (
                (self.phase == Phase.BIDDING and seat == self.bid_turn)
                or (self.phase == Phase.PLAYING and seat == self.current_turn)
            ),
        }
        return state
