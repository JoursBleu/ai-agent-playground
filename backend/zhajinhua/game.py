"""Zhajinhua (炸金花 / Three-Card Brag) — backend game engine."""

from __future__ import annotations

import os
import random
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


GAME_TYPE = "zhajinhua"


RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
RANK_TO_VALUE = {r: i for i, r in enumerate(RANK_ORDER)}
VALUE_TO_RANK = {v: r for r, v in RANK_TO_VALUE.items()}
SUITS = ("S", "H", "D", "C")


def _all_card_codes() -> List[str]:
    return [r + s for r in RANK_ORDER for s in SUITS]


class HandCategory(int, Enum):
    HIGH = 1
    PAIR = 2
    STRAIGHT = 3
    FLUSH = 4
    STRAIGHT_FLUSH = 5
    THREE_OF_A_KIND = 6


@dataclass(frozen=True)
class HandRank:
    category: HandCategory
    tiebreak: Tuple[int, ...]

    def as_dict(self) -> dict:
        return {
            "category": int(self.category),
            "category_name": self.category.name,
            "tiebreak": list(self.tiebreak),
        }


def evaluate_hand(codes: List[str]) -> HandRank:
    if len(codes) != 3:
        raise ValueError(f"hand must have exactly 3 cards, got {len(codes)}")
    ranks_v = sorted([RANK_TO_VALUE[c[0]] for c in codes], reverse=True)
    suits = [c[1] for c in codes]
    is_flush = len(set(suits)) == 1
    sorted_low = sorted(set(ranks_v))
    is_straight = False
    straight_top = ranks_v[0]
    if len(sorted_low) == 3:
        if sorted_low[2] - sorted_low[0] == 2:
            is_straight = True
            straight_top = sorted_low[2]
        elif sorted_low == [0, 1, 12]:
            is_straight = True
            straight_top = 1
    if len(set(ranks_v)) == 1:
        return HandRank(HandCategory.THREE_OF_A_KIND, tuple(ranks_v))
    if is_straight and is_flush:
        return HandRank(HandCategory.STRAIGHT_FLUSH, (straight_top,) + tuple(ranks_v))
    if is_flush:
        return HandRank(HandCategory.FLUSH, tuple(ranks_v))
    if is_straight:
        return HandRank(HandCategory.STRAIGHT, (straight_top,) + tuple(ranks_v))
    if len(set(ranks_v)) == 2:
        counts: Dict[int, int] = {}
        for r in ranks_v:
            counts[r] = counts.get(r, 0) + 1
        pair_v = max(r for r, c in counts.items() if c == 2)
        kicker = max(r for r, c in counts.items() if c == 1)
        return HandRank(HandCategory.PAIR, (pair_v, kicker))
    return HandRank(HandCategory.HIGH, tuple(ranks_v))


def compare_hands(a: HandRank, b: HandRank) -> int:
    if a.category != b.category:
        return 1 if int(a.category) > int(b.category) else -1
    if a.tiebreak > b.tiebreak:
        return 1
    if a.tiebreak < b.tiebreak:
        return -1
    return 0


class Phase(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"


class ZjhError(Exception):
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
    hand: List[str] = field(default_factory=list)
    seen: bool = False
    folded: bool = False
    is_owner: bool = False


@dataclass
class ActionRecord:
    seat: int
    action: str
    amount: int = 0
    target_seat: int = -1
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


class ZjhGame:
    N_SEATS = 3
    DEFAULT_CHIPS = 200
    DEFAULT_ANTE = 1
    DEFAULT_STAKE = 1
    DEFAULT_MAX_STAKE = 20
    TURN_SECONDS = 60
    THINK_SECONDS = 15

    game_type: str = GAME_TYPE

    def __init__(self, *, game_id, name, description="", rule_mode="builtin",
                 referee_url=None, seed=None,
                 starting_chips=None, ante=None, max_stake=None):
        self.game_id = game_id
        self.name = name
        self.description = description
        self.rule_mode = rule_mode
        self.referee_url = referee_url
        self._rng = random.Random(seed) if seed is not None else random.Random()

        self.starting_chips = int(starting_chips or os.environ.get("AAP_ZJH_CHIPS", self.DEFAULT_CHIPS))
        self.ante = int(ante or self.DEFAULT_ANTE)
        self.max_stake = int(max_stake or os.environ.get("AAP_ZJH_MAX_STAKE", self.DEFAULT_MAX_STAKE))

        self.created_at = time.time()
        self.last_active = self.created_at

        self.phase: Phase = Phase.WAITING
        self.players: List[Optional[Player]] = [None] * self.N_SEATS
        self.owner_seat: int = -1
        self.spectator_token: str = _new_token("spec")

        self.pot: int = 0
        self.stake: int = self.DEFAULT_STAKE
        self.dealer_seat: int = -1
        self.current_turn: int = -1
        self.turn_started_at: float = 0.0
        self.history: List[ActionRecord] = []
        self.winner_seat: int = -1
        self.last_winner_seat: int = -1
        self.round_no: int = 0

        self.disbanded: bool = False
        self.disbanded_reason: str = ""

        self.chat: List[ChatMsg] = []

        self._timeout_auto: bool = False

    def _touch(self):
        self.last_active = time.time()

    def seat_of(self, token: str) -> int:
        for i, p in enumerate(self.players):
            if p and p.token == token:
                return i
        raise ZjhError("invalid token")

    def is_owner(self, token: str) -> bool:
        try:
            return self.seat_of(token) == self.owner_seat
        except ZjhError:
            return False

    def is_spectator_token(self, tok: str) -> bool:
        return bool(tok) and tok == self.spectator_token

    def _active_seats(self) -> List[int]:
        return [i for i, p in enumerate(self.players) if p and not p.folded]

    def add_player(self, name: str, bio: str) -> Player:
        self._check_turn_timeout()
        self._touch()
        if self.disbanded:
            raise ZjhError("room has been disbanded")
        if self.phase != Phase.WAITING:
            raise ZjhError("game already started")
        name = (name or "").strip() or f"player-{secrets.token_hex(2)}"
        bio = (bio or "").strip()
        if not bio:
            raise ZjhError("bio is required: please introduce yourself before joining")
        if len(bio) > 1000:
            raise ZjhError("bio too long (>1000 chars)")
        for i in range(self.N_SEATS):
            if self.players[i] is None:
                p = Player(seat=i, name=name, bio=bio,
                           player_id=f"p_{secrets.token_hex(2)}",
                           token=_new_token("tok"),
                           chips=self.starting_chips)
                if self.owner_seat == -1:
                    self.owner_seat = i
                    p.is_owner = True
                self.players[i] = p
                if sum(1 for x in self.players if x is not None) == self.N_SEATS:
                    self._start_round()
                return p
        raise ZjhError("game already started")

    def leave_seat(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        seat = self.seat_of(token)
        is_owner = seat == self.owner_seat
        if is_owner:
            self.disband("owner left the seat")
            return {"disbanded": True, "seat": seat, "owner": True}
        if self.phase == Phase.PLAYING:
            raise ZjhError("game in progress, cannot leave seat (ask owner to disband)")
        self.players[seat] = None
        return {"disbanded": False, "seat": seat, "owner": False}

    def disband(self, reason: str):
        self.disbanded = True
        self.disbanded_reason = reason or "disbanded"
        self.phase = Phase.FINISHED
        self._touch()

    def _start_round(self):
        if any(p is None for p in self.players):
            return
        for p in self.players:
            if p.chips < self.ante:
                raise ZjhError(f"seat {p.seat} ({p.name}) cannot cover the ante")
        for p in self.players:
            p.chips -= self.ante
            p.bet_in_round = self.ante
            p.hand = []
            p.seen = False
            p.folded = False
        self.pot = self.ante * self.N_SEATS
        self.stake = self.DEFAULT_STAKE
        deck = _all_card_codes()
        self._rng.shuffle(deck)
        for i in range(self.N_SEATS):
            self.players[i].hand = deck[i * 3:(i + 1) * 3]
        if self.dealer_seat == -1:
            self.dealer_seat = self._rng.randrange(self.N_SEATS)
        else:
            self.dealer_seat = (self.dealer_seat + 1) % self.N_SEATS
        self.current_turn = (self.dealer_seat + 1) % self.N_SEATS
        self.turn_started_at = time.time()
        self.history = []
        self.winner_seat = -1
        self.phase = Phase.PLAYING
        self.round_no += 1

    def restart(self):
        if self.disbanded:
            raise ZjhError("room has been disbanded")
        if self.phase != Phase.FINISHED:
            raise ZjhError("current round is not finished yet")
        if any(p is None for p in self.players):
            raise ZjhError("need 3 seated players to restart")
        self._start_round()

    def _cost_for(self, seat: int, blind_stake: int) -> int:
        p = self.players[seat]
        return blind_stake * (2 if p.seen else 1)

    def _check_thinking_guard(self):
        if self._timeout_auto:
            return
        elapsed = time.time() - self.turn_started_at
        if elapsed < self.THINK_SECONDS:
            remaining = self.THINK_SECONDS - elapsed
            raise ZjhError(
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
                if p is not None and not p.folded:
                    self._do_fold(self.current_turn, note="timeout")
            finally:
                self._timeout_auto = False

    def look(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        if self.phase != Phase.PLAYING:
            raise ZjhError("not in playing phase")
        seat = self.seat_of(token)
        p = self.players[seat]
        if p.folded:
            raise ZjhError("already folded")
        if p.seen:
            raise ZjhError("you have already looked")
        p.seen = True
        self.history.append(ActionRecord(seat=seat, action="look", timestamp=time.time()))
        return {"action": "look", "hand": list(p.hand)}

    def call(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        if self.phase != Phase.PLAYING:
            raise ZjhError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise ZjhError("not your turn")
        self._check_thinking_guard()
        p = self.players[seat]
        if p.folded:
            raise ZjhError("already folded")
        cost = self._cost_for(seat, self.stake)
        if p.chips < cost:
            raise ZjhError(f"not enough chips to call (need {cost}, have {p.chips})")
        p.chips -= cost
        p.bet_in_round += cost
        self.pot += cost
        self.history.append(ActionRecord(seat=seat, action="call", amount=cost, timestamp=time.time()))
        self._advance_turn()
        return {"action": "call", "cost": cost}

    def raise_bet(self, token: str, new_stake: int) -> dict:
        self._check_turn_timeout()
        self._touch()
        if self.phase != Phase.PLAYING:
            raise ZjhError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise ZjhError("not your turn")
        self._check_thinking_guard()
        p = self.players[seat]
        if p.folded:
            raise ZjhError("already folded")
        if not isinstance(new_stake, int) or new_stake <= self.stake:
            raise ZjhError(f"new stake must be > current stake ({self.stake})")
        if new_stake > self.max_stake:
            raise ZjhError(f"new stake must be ≤ max_stake ({self.max_stake})")
        cost = self._cost_for(seat, new_stake)
        if p.chips < cost:
            raise ZjhError(f"not enough chips to raise to {new_stake} (need {cost}, have {p.chips})")
        p.chips -= cost
        p.bet_in_round += cost
        self.pot += cost
        self.stake = new_stake
        self.history.append(ActionRecord(seat=seat, action="raise", amount=cost,
                                         note=f"stake={new_stake}", timestamp=time.time()))
        self._advance_turn()
        return {"action": "raise", "cost": cost, "stake": new_stake}

    def fold(self, token: str) -> dict:
        self._check_turn_timeout()
        self._touch()
        if self.phase != Phase.PLAYING:
            raise ZjhError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise ZjhError("not your turn")
        self._check_thinking_guard()
        p = self.players[seat]
        if p.folded:
            raise ZjhError("already folded")
        return self._do_fold(seat)

    def _do_fold(self, seat: int, *, note: str = "") -> dict:
        p = self.players[seat]
        p.folded = True
        action = "timeout_fold" if note == "timeout" else "fold"
        self.history.append(ActionRecord(seat=seat, action=action, note=note, timestamp=time.time()))
        if self._check_round_end():
            return {"action": action, "round_ended": True, "winner": self.winner_seat}
        self._advance_turn()
        return {"action": action, "round_ended": False}

    def compare(self, token: str, target_seat: int) -> dict:
        self._check_turn_timeout()
        self._touch()
        if self.phase != Phase.PLAYING:
            raise ZjhError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise ZjhError("not your turn")
        self._check_thinking_guard()
        p = self.players[seat]
        if p.folded:
            raise ZjhError("already folded")
        if not p.seen:
            raise ZjhError("you must look at your hand before comparing")
        if target_seat == seat:
            raise ZjhError("cannot compare against yourself")
        if not (0 <= target_seat < self.N_SEATS):
            raise ZjhError("invalid target seat")
        tp = self.players[target_seat]
        if tp is None or tp.folded:
            raise ZjhError("target seat is not active")
        cost = self.stake * 2
        if p.chips < cost:
            raise ZjhError(f"not enough chips to compare (need {cost}, have {p.chips})")
        p.chips -= cost
        p.bet_in_round += cost
        self.pot += cost
        a_rank = evaluate_hand(p.hand)
        b_rank = evaluate_hand(tp.hand)
        cmp = compare_hands(a_rank, b_rank)
        if cmp > 0:
            tp.folded = True
            loser, winner = target_seat, seat
        elif cmp < 0:
            p.folded = True
            loser, winner = seat, target_seat
        else:
            p.folded = True
            loser, winner = seat, target_seat
        note = f"vs seat={target_seat} winner=seat{winner} loser=seat{loser} cmp={cmp}"
        self.history.append(ActionRecord(seat=seat, action="compare", amount=cost,
                                         target_seat=target_seat, note=note,
                                         timestamp=time.time()))
        result = {
            "action": "compare",
            "cost": cost,
            "target_seat": target_seat,
            "winner_seat": winner,
            "loser_seat": loser,
            "your_hand_rank": a_rank.as_dict(),
            "target_hand_rank": b_rank.as_dict(),
            "reveal": {"self": list(p.hand), "target": list(tp.hand)},
        }
        if self._check_round_end():
            result["round_ended"] = True
            result["winner"] = self.winner_seat
            return result
        result["round_ended"] = False
        self._advance_turn()
        return result

    def _advance_turn(self):
        active = self._active_seats()
        if not active:
            return
        nxt = self.current_turn
        for _ in range(self.N_SEATS):
            nxt = (nxt + 1) % self.N_SEATS
            if nxt in active:
                self.current_turn = nxt
                self.turn_started_at = time.time()
                return

    def _check_round_end(self) -> bool:
        active = self._active_seats()
        if len(active) <= 1:
            if active:
                w = active[0]
                p = self.players[w]
                p.chips += self.pot
                self.winner_seat = w
                self.last_winner_seat = w
                self.history.append(ActionRecord(seat=w, action="win", amount=self.pot, timestamp=time.time()))
            self.phase = Phase.FINISHED
            self.current_turn = -1
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
                    "chips": 0, "bet_in_round": 0, "seen": False, "folded": False}
        return {
            "seat": p.seat,
            "joined": True,
            "name": p.name,
            "bio": p.bio,
            "chips": p.chips,
            "bet_in_round": p.bet_in_round,
            "seen": p.seen,
            "folded": p.folded,
        }

    def public_state(self) -> dict:
        self._check_turn_timeout()
        return {
            "game_type": GAME_TYPE,
            "game_id": self.game_id,
            "name": self.name,
            "description": self.description,
            "phase": self.phase.value,
            "rule_mode": self.rule_mode,
            "round_no": self.round_no,
            "owner_seat": self.owner_seat,
            "dealer_seat": self.dealer_seat,
            "current_turn": self.current_turn,
            "pot": self.pot,
            "stake": self.stake,
            "max_stake": self.max_stake,
            "ante": self.ante,
            "starting_chips": self.starting_chips,
            "winner_seat": self.winner_seat,
            "last_winner_seat": self.last_winner_seat,
            "disbanded": self.disbanded,
            "disbanded_reason": self.disbanded_reason,
            "players": [
                {**self._player_pub(self.players[i]), "seat": i}
                for i in range(self.N_SEATS)
            ],
            "history": [
                {"seat": h.seat, "action": h.action, "amount": h.amount,
                 "target_seat": h.target_seat, "note": h.note, "timestamp": h.timestamp}
                for h in self.history[-40:]
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
        state["you"] = {
            "seat": seat,
            "player_id": p.player_id,
            "name": p.name,
            "bio": p.bio,
            "chips": p.chips,
            "bet_in_round": p.bet_in_round,
            "seen": p.seen,
            "folded": p.folded,
            "is_owner": (seat == self.owner_seat),
            "is_your_turn": (seat == self.current_turn),
            "hand": list(p.hand) if p.seen else [],
            "call_cost": self._cost_for(seat, self.stake),
            "compare_cost": self.stake * 2,
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
            raise ZjhError("chat text empty")
        if len(text) > 500:
            raise ZjhError("chat too long (>500 chars)")
        msg = ChatMsg(seat=seat, name=p.name, text=text, timestamp=time.time())
        self.chat.append(msg)
        if len(self.chat) > 200:
            self.chat = self.chat[-200:]
        return msg

    def chat_since(self, since_ts: float = 0.0, limit: int = 50) -> List[ChatMsg]:
        out = [m for m in self.chat if m.timestamp > since_ts]
        return out[-limit:]


GameError = ZjhError
