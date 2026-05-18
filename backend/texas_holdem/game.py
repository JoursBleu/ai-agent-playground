"""Texas Hold'em (德州扑克) — backend game engine.

No-Limit Hold'em with 2-9 seats, fixed blinds (SB=1, BB=2 by default).
Implements: pre-flop / flop / turn / river / showdown, fold/check/call/raise/allin,
basic side-pot resolution, 7-card hand evaluation via best-5-of-7 brute force.
"""

from __future__ import annotations

import itertools
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


GAME_TYPE = "texas_holdem"


RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
RANK_TO_VALUE = {r: i + 2 for i, r in enumerate(RANK_ORDER)}  # 2..14
SUITS = ("S", "H", "D", "C")


def _all_card_codes() -> List[str]:
    return [r + s for r in RANK_ORDER for s in SUITS]


class HandCategory(int, Enum):
    HIGH_CARD = 1
    PAIR = 2
    TWO_PAIR = 3
    THREE_OF_A_KIND = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9


@dataclass(frozen=True)
class HandRank:
    category: HandCategory
    tiebreak: Tuple[int, ...]
    best5: Tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "category": int(self.category),
            "category_name": self.category.name,
            "tiebreak": list(self.tiebreak),
            "best5": list(self.best5),
        }

    def key(self) -> Tuple[int, ...]:
        return (int(self.category),) + tuple(self.tiebreak)


def _eval_5(cards):
    vals = sorted((RANK_TO_VALUE[c[0]] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1
    uniq = sorted(set(vals), reverse=True)
    is_straight = False
    straight_top = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            is_straight = True
            straight_top = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_top = 5
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    by_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    if is_straight and is_flush:
        return HandCategory.STRAIGHT_FLUSH, (straight_top,)
    if by_count[0][1] == 4:
        quad = by_count[0][0]
        kicker = by_count[1][0]
        return HandCategory.FOUR_OF_A_KIND, (quad, kicker)
    if by_count[0][1] == 3 and by_count[1][1] == 2:
        return HandCategory.FULL_HOUSE, (by_count[0][0], by_count[1][0])
    if is_flush:
        return HandCategory.FLUSH, tuple(vals)
    if is_straight:
        return HandCategory.STRAIGHT, (straight_top,)
    if by_count[0][1] == 3:
        trips = by_count[0][0]
        kickers = sorted((v for v in vals if v != trips), reverse=True)
        return HandCategory.THREE_OF_A_KIND, (trips, kickers[0], kickers[1])
    if by_count[0][1] == 2 and by_count[1][1] == 2:
        hi = max(by_count[0][0], by_count[1][0])
        lo = min(by_count[0][0], by_count[1][0])
        kicker = next(v for v in vals if v != hi and v != lo)
        return HandCategory.TWO_PAIR, (hi, lo, kicker)
    if by_count[0][1] == 2:
        pair = by_count[0][0]
        kickers = sorted((v for v in vals if v != pair), reverse=True)
        return HandCategory.PAIR, (pair, kickers[0], kickers[1], kickers[2])
    return HandCategory.HIGH_CARD, tuple(vals)


def evaluate_best5(cards):
    if len(cards) < 5 or len(cards) > 7:
        raise ValueError(f"need 5..7 cards, got {len(cards)}")
    best = None
    for combo in itertools.combinations(cards, 5):
        cat, tb = _eval_5(list(combo))
        if best is None or (int(cat), tb) > (int(best[0]), best[1]):
            best = (cat, tb, combo)
    return HandRank(category=best[0], tiebreak=best[1], best5=best[2])


def compare_hands(a, b):
    if a.key() > b.key():
        return 1
    if a.key() < b.key():
        return -1
    return 0


class Phase(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class TexasError(Exception):
    pass


@dataclass
class Player:
    seat: int
    name: str
    bio: str
    player_id: str
    token: str
    chips: int
    bet_in_round: int = 0
    total_bet: int = 0
    hand: List[str] = field(default_factory=list)
    folded: bool = False
    all_in: bool = False
    has_acted_this_street: bool = False
    is_owner: bool = False


@dataclass
class ActionRecord:
    seat: int
    action: str
    amount: int = 0
    note: str = ""
    timestamp: float = 0.0


@dataclass
class ChatMsg:
    seat: int
    name: str
    text: str
    timestamp: float


def _new_token(prefix: str = "tok") -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class TexasGame:
    N_SEATS = 6
    DEFAULT_CHIPS = 400
    DEFAULT_SB = 1
    DEFAULT_BB = 2
    TURN_SECONDS = 60
    THINK_SECONDS = 10

    game_type: str = GAME_TYPE

    def __init__(self, *, game_id, name, description="", rule_mode="builtin",
                 referee_url=None, seed=None,
                 n_seats=None, starting_chips=None, small_blind=None, big_blind=None):
        self.game_id = game_id
        self.name = name
        self.description = description
        self.rule_mode = rule_mode
        self.referee_url = referee_url
        self._rng = random.Random(seed) if seed is not None else random.Random()

        self.n_seats = int(n_seats or os.environ.get("AAP_TEXAS_SEATS", self.N_SEATS))
        if not (2 <= self.n_seats <= 9):
            raise ValueError("n_seats must be between 2 and 9")
        self.starting_chips = int(starting_chips or os.environ.get("AAP_TEXAS_CHIPS", self.DEFAULT_CHIPS))
        self.small_blind = int(small_blind or os.environ.get("AAP_TEXAS_SB", self.DEFAULT_SB))
        self.big_blind = int(big_blind or os.environ.get("AAP_TEXAS_BB", self.DEFAULT_BB))
        if self.small_blind <= 0 or self.big_blind <= self.small_blind:
            raise ValueError("require 0 < small_blind < big_blind")

        self.created_at = time.time()
        self.last_active = self.created_at

        self.phase: Phase = Phase.WAITING
        self.street: Street = Street.PREFLOP
        self.players: List[Optional[Player]] = [None] * self.n_seats
        self.owner_seat: int = -1
        self.spectator_token: str = _new_token("spec")

        self.community: List[str] = []
        self._deck: List[str] = []
        self.pot: int = 0
        self.current_bet: int = 0
        self.last_raise_size: int = 0

        self.dealer_seat: int = -1
        self.current_turn: int = -1
        self.turn_started_at: float = 0.0
        self.history: List[ActionRecord] = []
        self.winners: List[int] = []
        self.last_showdown: List[dict] = []
        self.round_no: int = 0

        self.disbanded: bool = False
        self.disbanded_reason: str = ""

        self.chat: List[ChatMsg] = []
        self._timeout_auto: bool = False
        self._hand_start_chips: Dict[int, int] = {}

    def _touch(self):
        self.last_active = time.time()

    def seat_of(self, token: str) -> int:
        for i, p in enumerate(self.players):
            if p and p.token == token:
                return i
        raise TexasError("invalid token")

    def is_owner(self, token: str) -> bool:
        try:
            return self.seat_of(token) == self.owner_seat
        except TexasError:
            return False

    def is_spectator_token(self, tok: str) -> bool:
        return bool(tok) and tok == self.spectator_token

    def _seats_in_hand(self) -> List[int]:
        return [i for i, p in enumerate(self.players) if p and not p.folded]

    def _seats_can_act(self) -> List[int]:
        return [i for i, p in enumerate(self.players)
                if p and not p.folded and not p.all_in]

    def add_player(self, name: str, bio: str) -> Player:
        self._check_turn_timeout()
        self._touch()
        if self.disbanded:
            raise TexasError("room has been disbanded")
        if self.phase == Phase.PLAYING:
            raise TexasError("hand in progress, cannot join until next hand")
        name = (name or "").strip() or f"player-{secrets.token_hex(2)}"
        bio = (bio or "").strip()
        if not bio:
            raise TexasError("bio is required: please introduce yourself before joining")
        if len(bio) > 1000:
            raise TexasError("bio too long (>1000 chars)")
        for i in range(self.n_seats):
            if self.players[i] is None:
                p = Player(seat=i, name=name, bio=bio,
                           player_id=f"p_{secrets.token_hex(2)}",
                           token=_new_token("tok"),
                           chips=self.starting_chips)
                if self.owner_seat == -1:
                    self.owner_seat = i
                    p.is_owner = True
                self.players[i] = p
                seated = sum(1 for x in self.players if x is not None)
                if seated == self.n_seats and self.phase == Phase.WAITING:
                    self._start_hand()
                return p
        raise TexasError("table full")

    def leave_seat(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat = self.seat_of(token)
        is_owner = seat == self.owner_seat
        if is_owner:
            self.disband("owner left the seat")
            return {"disbanded": True, "seat": seat, "owner": True}
        if self.phase == Phase.PLAYING:
            raise TexasError("hand in progress, cannot leave (ask owner to disband)")
        self.players[seat] = None
        return {"disbanded": False, "seat": seat, "owner": False}

    def disband(self, reason: str):
        self.disbanded = True
        self.disbanded_reason = reason or "disbanded"
        self.phase = Phase.FINISHED
        self._touch()

    def restart(self):
        if self.disbanded:
            raise TexasError("room has been disbanded")
        if self.phase != Phase.FINISHED:
            raise TexasError("current hand is not finished yet")
        live = [p for p in self.players if p is not None and p.chips > 0]
        if len(live) < 2:
            raise TexasError("need at least 2 seated players with chips to restart")
        self._start_hand()

    def _start_hand(self):
        seated = [i for i, p in enumerate(self.players) if p is not None]
        if len(seated) < 2:
            return
        for p in self.players:
            if p is None:
                continue
            p.bet_in_round = 0
            p.total_bet = 0
            p.hand = []
            p.folded = (p.chips <= 0)
            p.all_in = False
            p.has_acted_this_street = False
        self._hand_start_chips = {i: (p.chips if p is not None else 0)
                                  for i, p in enumerate(self.players)}
        deck = _all_card_codes()
        self._rng.shuffle(deck)
        self._deck = deck
        active = [i for i in seated if not self.players[i].folded]
        if len(active) < 2:
            self.phase = Phase.FINISHED
            self.disbanded = True
            self.disbanded_reason = "not enough players with chips"
            return
        for _ in range(2):
            for i in active:
                self.players[i].hand.append(self._deck.pop())
        self.community = []
        self.pot = 0
        self.current_bet = 0
        self.last_raise_size = self.big_blind
        self.history = []
        self.winners = []
        self.last_showdown = []
        self.street = Street.PREFLOP

        if self.dealer_seat == -1 or self.dealer_seat not in active:
            self.dealer_seat = active[self._rng.randrange(len(active))]
        else:
            self.dealer_seat = self._next_active(self.dealer_seat, active)

        if len(active) == 2:
            sb_seat = self.dealer_seat
            bb_seat = self._next_active(self.dealer_seat, active)
            first_to_act = self.dealer_seat
        else:
            sb_seat = self._next_active(self.dealer_seat, active)
            bb_seat = self._next_active(sb_seat, active)
            first_to_act = self._next_active(bb_seat, active)
        self._post_blind(sb_seat, self.small_blind, "sb")
        self._post_blind(bb_seat, self.big_blind, "bb")
        self.current_bet = self.big_blind
        self.last_raise_size = self.big_blind
        self.current_turn = first_to_act
        self.turn_started_at = time.time()
        self.phase = Phase.PLAYING
        self.round_no += 1

    def _next_active(self, seat: int, active: List[int]) -> int:
        n = self.n_seats
        for k in range(1, n + 1):
            cand = (seat + k) % n
            if cand in active:
                return cand
        return seat

    def _post_blind(self, seat: int, amt: int, kind: str):
        p = self.players[seat]
        put = min(p.chips, amt)
        p.chips -= put
        p.bet_in_round += put
        p.total_bet += put
        self.pot += put
        if p.chips == 0:
            p.all_in = True
        self.history.append(ActionRecord(seat=seat, action=kind, amount=put,
                                         timestamp=time.time()))

    def _check_thinking_guard(self):
        if self._timeout_auto:
            return
        elapsed = time.time() - self.turn_started_at
        if elapsed < self.THINK_SECONDS:
            remaining = self.THINK_SECONDS - elapsed
            raise TexasError(
                f"thinking phase: must wait {remaining:.1f}s more (action window opens at t={self.THINK_SECONDS:.0f}s)"
            )

    def _check_turn_timeout(self):
        if self.phase != Phase.PLAYING or self.current_turn < 0:
            return
        elapsed = time.time() - self.turn_started_at
        if elapsed > self.TURN_SECONDS:
            self._timeout_auto = True
            try:
                p = self.players[self.current_turn]
                if p is not None and not p.folded and not p.all_in:
                    self._do_fold(self.current_turn, note="timeout")
            finally:
                self._timeout_auto = False

    def _require_turn(self, token: str):
        if self.phase != Phase.PLAYING:
            raise TexasError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise TexasError("not your turn")
        p = self.players[seat]
        if p.folded:
            raise TexasError("already folded")
        if p.all_in:
            raise TexasError("you are all-in; no action required")
        return seat, p

    def fold(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat, _p = self._require_turn(token)
        self._check_thinking_guard()
        return self._do_fold(seat)

    def _do_fold(self, seat: int, *, note: str = "") -> dict:
        p = self.players[seat]
        p.folded = True
        p.has_acted_this_street = True
        action = "timeout_fold" if note == "timeout" else "fold"
        self.history.append(ActionRecord(seat=seat, action=action, note=note,
                                         timestamp=time.time()))
        if self._check_hand_end_after_action():
            return {"action": action, "hand_ended": True}
        self._advance_or_next_street()
        return {"action": action, "hand_ended": False}

    def check(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat, p = self._require_turn(token)
        self._check_thinking_guard()
        if p.bet_in_round < self.current_bet:
            raise TexasError(f"cannot check: must call {self.current_bet - p.bet_in_round}")
        p.has_acted_this_street = True
        self.history.append(ActionRecord(seat=seat, action="check", timestamp=time.time()))
        self._advance_or_next_street()
        return {"action": "check"}

    def call(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat, p = self._require_turn(token)
        self._check_thinking_guard()
        need = self.current_bet - p.bet_in_round
        if need <= 0:
            return self.check(token)
        pay = min(p.chips, need)
        p.chips -= pay
        p.bet_in_round += pay
        p.total_bet += pay
        self.pot += pay
        if p.chips == 0:
            p.all_in = True
        p.has_acted_this_street = True
        self.history.append(ActionRecord(seat=seat, action="call", amount=pay,
                                         timestamp=time.time()))
        self._advance_or_next_street()
        return {"action": "call", "amount": pay, "all_in": p.all_in}

    def raise_to(self, token: str, target: int) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat, p = self._require_turn(token)
        self._check_thinking_guard()
        if not isinstance(target, int) or target <= self.current_bet:
            raise TexasError(f"raise target must be > current bet ({self.current_bet})")
        delta = target - p.bet_in_round
        if delta <= 0:
            raise TexasError("nothing to add")
        raise_inc = target - self.current_bet
        is_allin = (delta >= p.chips)
        if not is_allin and raise_inc < self.last_raise_size:
            raise TexasError(f"min raise increment is {self.last_raise_size} (target >= {self.current_bet + self.last_raise_size})")
        pay = min(p.chips, delta)
        if pay == 0:
            raise TexasError("not enough chips to raise")
        p.chips -= pay
        p.bet_in_round += pay
        p.total_bet += pay
        self.pot += pay
        new_bet = p.bet_in_round
        if p.chips == 0:
            p.all_in = True
        if new_bet > self.current_bet:
            if (new_bet - self.current_bet) >= self.last_raise_size:
                self.last_raise_size = new_bet - self.current_bet
                for other in self.players:
                    if other is None or other.seat == seat:
                        continue
                    if not other.folded and not other.all_in:
                        other.has_acted_this_street = False
            self.current_bet = new_bet
        p.has_acted_this_street = True
        self.history.append(ActionRecord(seat=seat, action="raise",
                                         amount=pay,
                                         note=f"to={new_bet}",
                                         timestamp=time.time()))
        self._advance_or_next_street()
        return {"action": "raise", "amount": pay, "to": new_bet, "all_in": p.all_in}

    def all_in(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat, p = self._require_turn(token)
        self._check_thinking_guard()
        target = p.bet_in_round + p.chips
        if target > self.current_bet:
            return self.raise_to(token, target)
        return self.call(token)

    def _advance_or_next_street(self):
        in_hand = self._seats_in_hand()
        if len(in_hand) <= 1:
            self._end_hand_one_left()
            return

        cur = self.current_turn
        n = self.n_seats
        for k in range(1, n + 1):
            cand = (cur + k) % n
            p = self.players[cand]
            if p is None or p.folded or p.all_in:
                continue
            if (p.bet_in_round < self.current_bet) or (not p.has_acted_this_street):
                self.current_turn = cand
                self.turn_started_at = time.time()
                return

        self._next_street()

    def _next_street(self):
        for p in self.players:
            if p is None:
                continue
            p.bet_in_round = 0
            p.has_acted_this_street = False
        self.current_bet = 0
        self.last_raise_size = self.big_blind

        if self.street == Street.PREFLOP:
            self._deal_community(3)
            self.street = Street.FLOP
        elif self.street == Street.FLOP:
            self._deal_community(1)
            self.street = Street.TURN
        elif self.street == Street.TURN:
            self._deal_community(1)
            self.street = Street.RIVER
        elif self.street == Street.RIVER:
            self.street = Street.SHOWDOWN
            self._showdown()
            return

        active = self._seats_can_act()
        if not active:
            self._fast_forward_to_showdown()
            return
        cur = self.dealer_seat
        n = self.n_seats
        for k in range(1, n + 1):
            cand = (cur + k) % n
            p = self.players[cand]
            if p is None or p.folded or p.all_in:
                continue
            self.current_turn = cand
            self.turn_started_at = time.time()
            return

    def _deal_community(self, n: int):
        if self._deck:
            self._deck.pop()
        for _ in range(n):
            if self._deck:
                self.community.append(self._deck.pop())

    def _fast_forward_to_showdown(self):
        while self.street != Street.RIVER:
            if self.street == Street.PREFLOP:
                if len(self.community) < 3:
                    self._deal_community(3)
                self.street = Street.FLOP
            elif self.street == Street.FLOP:
                if len(self.community) < 4:
                    self._deal_community(1)
                self.street = Street.TURN
            elif self.street == Street.TURN:
                if len(self.community) < 5:
                    self._deal_community(1)
                self.street = Street.RIVER
        self.street = Street.SHOWDOWN
        self._showdown()

    def _end_hand_one_left(self):
        in_hand = self._seats_in_hand()
        assert len(in_hand) == 1
        w = in_hand[0]
        self.players[w].chips += self.pot
        self.history.append(ActionRecord(seat=w, action="win", amount=self.pot,
                                         note="opponents folded",
                                         timestamp=time.time()))
        self.last_showdown = [{"seat": w, "won": self.pot, "reason": "uncontested"}]
        self.winners = [w]
        self.pot = 0
        self.phase = Phase.FINISHED
        self.current_turn = -1

    def _showdown(self):
        contenders = self._seats_in_hand()
        ranks = {}
        for s in contenders:
            cards = list(self.players[s].hand) + list(self.community)
            ranks[s] = evaluate_best5(cards)

        contribs = sorted({self.players[s].total_bet for s in range(self.n_seats)
                           if self.players[s] is not None and self.players[s].total_bet > 0})
        prev = 0
        payouts = {s: 0 for s in range(self.n_seats)}
        for level in contribs:
            layer_total = 0
            eligible_seats = []
            for s in range(self.n_seats):
                pl = self.players[s]
                if pl is None or pl.total_bet <= 0:
                    continue
                contrib = min(pl.total_bet, level) - prev
                if contrib > 0:
                    layer_total += contrib
            for s in contenders:
                pl = self.players[s]
                if pl.total_bet >= level:
                    eligible_seats.append(s)
            if not eligible_seats or layer_total == 0:
                prev = level
                continue
            best_key = max(ranks[s].key() for s in eligible_seats)
            winners = [s for s in eligible_seats if ranks[s].key() == best_key]
            share = layer_total // len(winners)
            rem = layer_total - share * len(winners)
            order = sorted(winners, key=lambda s: ((s - self.dealer_seat - 1) % self.n_seats))
            for i, s in enumerate(order):
                payouts[s] += share + (1 if i < rem else 0)
            prev = level

        for s, amt in payouts.items():
            if amt > 0:
                self.players[s].chips += amt
                self.history.append(ActionRecord(seat=s, action="win", amount=amt,
                                                 note=f"showdown {ranks[s].category.name}" if s in ranks else "showdown",
                                                 timestamp=time.time()))
        self.last_showdown = [
            {"seat": s,
             "hand": list(self.players[s].hand),
             "rank": ranks[s].as_dict(),
             "won": payouts[s]}
            for s in contenders
        ]
        self.winners = [s for s in range(self.n_seats) if payouts.get(s, 0) > 0]
        self.pot = 0
        self.phase = Phase.FINISHED
        self.current_turn = -1

    def _check_hand_end_after_action(self) -> bool:
        if len(self._seats_in_hand()) <= 1:
            self._end_hand_one_left()
            return True
        return False

    def _turn_clock_info(self) -> dict:
        if self.phase != Phase.PLAYING or self.current_turn < 0:
            return {"phase": self.phase.value, "active": False, "can_act": False,
                    "total_seconds": self.TURN_SECONDS,
                    "think_seconds": self.THINK_SECONDS,
                    "action_seconds": self.TURN_SECONDS - self.THINK_SECONDS}
        elapsed = time.time() - self.turn_started_at
        remaining_think = max(0.0, self.THINK_SECONDS - elapsed)
        remaining_total = max(0.0, self.TURN_SECONDS - elapsed)
        if elapsed < self.THINK_SECONDS:
            remaining_action = self.TURN_SECONDS - self.THINK_SECONDS
        else:
            remaining_action = remaining_total
        return {
            "phase": self.phase.value,
            "active": True,
            "turn_seat": self.current_turn,
            "turn_started_at": self.turn_started_at,
            "elapsed": round(elapsed, 2),
            "think_seconds": self.THINK_SECONDS,
            "total_seconds": self.TURN_SECONDS,
            "action_seconds": self.TURN_SECONDS - self.THINK_SECONDS,
            "thinking_remaining": round(remaining_think, 2),
            "action_remaining": round(remaining_action, 2),
            "can_act": remaining_think <= 0,
        }

    def _player_pub(self, p) -> dict:
        if p is None:
            return {"seat": -1, "joined": False, "name": None, "bio": "",
                    "chips": 0, "bet_in_round": 0, "total_bet": 0,
                    "folded": False, "all_in": False}
        return {
            "seat": p.seat,
            "joined": True,
            "name": p.name,
            "bio": p.bio,
            "chips": p.chips,
            "bet_in_round": p.bet_in_round,
            "total_bet": p.total_bet,
            "folded": p.folded,
            "all_in": p.all_in,
        }

    # Per-hand entry fee burned from each seat that participated.
    ENTRY_FEE = 1

    def compute_settlement(self) -> Dict[int, int]:
        """Per-seat point delta for the just-finished hand.

        Points delta = (chip_delta_during_hand) - ENTRY_FEE
        Chip deltas already reflect proper poker rules (raises, all-in,
        side pots, blinds) since they come from the in-hand chip accounting.
        Only seats that were dealt this hand (present in _hand_start_chips)
        pay the entry fee.
        """
        if self.phase != Phase.FINISHED:
            return {}
        out: Dict[int, int] = {}
        for i in range(self.n_seats):
            p = self.players[i]
            if p is None:
                continue
            if i not in self._hand_start_chips:
                continue
            start = self._hand_start_chips[i]
            out[i] = (p.chips - start) - self.ENTRY_FEE
        return out

    def public_state(self) -> dict:
        self._check_turn_timeout()
        return {
            "game_type": GAME_TYPE,
            "game_id": self.game_id,
            "name": self.name,
            "description": self.description,
            "phase": self.phase.value,
            "street": self.street.value,
            "rule_mode": self.rule_mode,
            "round_no": self.round_no,
            "n_seats": self.n_seats,
            "owner_seat": self.owner_seat,
            "dealer_seat": self.dealer_seat,
            "current_turn": self.current_turn,
            "pot": self.pot,
            "current_bet": self.current_bet,
            "min_raise": self.last_raise_size,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "starting_chips": self.starting_chips,
            "community": list(self.community),
            "winners": list(self.winners),
            "last_showdown": list(self.last_showdown),
            "disbanded": self.disbanded,
            "disbanded_reason": self.disbanded_reason,
            "players": [
                {**self._player_pub(self.players[i]), "seat": i}
                for i in range(self.n_seats)
            ],
            "history": [
                {"seat": h.seat, "action": h.action, "amount": h.amount,
                 "note": h.note, "timestamp": h.timestamp}
                for h in self.history[-60:]
            ],
            "chat": [
                {"seat": m.seat, "name": m.name, "text": m.text, "timestamp": m.timestamp}
                for m in self.chat[-50:]
            ],
            "turn_clock": self._turn_clock_info(),
        }

    def private_state(self, token: str) -> dict:
        seat = self.seat_of(token)
        state = self.public_state()
        p = self.players[seat]
        call_amt = max(0, self.current_bet - p.bet_in_round)
        min_raise_to = self.current_bet + self.last_raise_size
        state["you"] = {
            "seat": seat,
            "player_id": p.player_id,
            "name": p.name,
            "bio": p.bio,
            "chips": p.chips,
            "bet_in_round": p.bet_in_round,
            "total_bet": p.total_bet,
            "folded": p.folded,
            "all_in": p.all_in,
            "is_owner": (seat == self.owner_seat),
            "is_your_turn": (seat == self.current_turn),
            "hand": list(p.hand),
            "call_amount": call_amt,
            "min_raise_to": min_raise_to,
            "max_raise_to": p.bet_in_round + p.chips,
            "can_check": (call_amt == 0),
        }
        return state

    def omniscient_state(self) -> dict:
        state = self.public_state()
        for i, p in enumerate(self.players):
            if p is not None:
                state["players"][i]["hand"] = list(p.hand)
        return state

    def post_chat(self, token: str, text: str) -> ChatMsg:
        self._touch()
        seat = self.seat_of(token)
        p = self.players[seat]
        text = (text or "").strip()
        if not text:
            raise TexasError("chat text empty")
        if len(text) > 500:
            raise TexasError("chat too long (>500 chars)")
        msg = ChatMsg(seat=seat, name=p.name, text=text, timestamp=time.time())
        self.chat.append(msg)
        if len(self.chat) > 200:
            self.chat = self.chat[-200:]
        return msg

    def chat_since(self, since_ts: float = 0.0, limit: int = 50) -> List[ChatMsg]:
        out = [m for m in self.chat if m.timestamp > since_ts]
        return out[-limit:]


GameError = TexasError
