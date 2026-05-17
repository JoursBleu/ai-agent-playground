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
    bio: str = ""
    hand: List[Card] = field(default_factory=list)
    is_landlord: bool = False


@dataclass
class TrickRecord:
    seat: int
    cards: List[str]            # card codes; [] = pass
    pattern: Optional[str]      # category name; None = pass
    timestamp: float


@dataclass
class ChatMessage:
    seat: int
    name: str
    text: str
    timestamp: float


class GameError(Exception):
    pass


class Game:
    # ---- turn-clock rules (see docs/AGENT_API.md) ----
    # Every turn (bidding or playing) gets TURN_TOTAL_SECONDS = 20s.
    # The first THINK_SECONDS = 15s is a mandatory thinking window: any
    # action submitted during this window is rejected with GameError
    # "thinking phase, must wait until t=15s". Only the final
    # ACTION_SECONDS = 5s is a valid action window. If the player has
    # not acted by t=20s, the server auto-resolves: bid -> 0 (pass),
    # play -> pass (or smallest single card if leader).
    THINK_SECONDS: float = 15.0
    ACTION_SECONDS: float = 45.0
    TURN_TOTAL_SECONDS: float = 60.0

    def __init__(
        self,
        game_id: str,
        name: str = "",
        description: str = "",
        rule_mode: str = "builtin",
        referee_url: Optional[str] = None,
        seed: Optional[int] = None,
    ):
        self.game_id = game_id
        self.name = (name or "").strip() or game_id
        self.description = (description or "").strip()
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
        self.chat: List[ChatMessage] = []
        self.turn_started_at: float = 0.0
        self._timeout_auto: bool = False
        self.owner_seat: int = -1       # first joiner becomes owner
        self.disbanded: bool = False
        self.disbanded_reason: str = ""
        # opaque omniscient-spectator token; anyone with this can see all hands
        self.spectator_token: str = secrets.token_hex(8)

        self._rng = random.Random(seed)
        self.created_at = time.time()
        self.last_active: float = self.created_at

    def touch(self) -> None:
        """Mark room as recently active for idle reaper."""
        self.last_active = time.time()

    # ---- joining --------------------------------------------------------

    def add_player(self, name: str, bio: str = "") -> Player:
        if self.phase != Phase.WAITING:
            raise GameError("game already started")
        bio = (bio or "").strip()
        if not bio:
            raise GameError("bio is required: please introduce yourself before joining")
        if len(bio) > self.MAX_BIO_LEN:
            raise GameError(f"bio too long (>{self.MAX_BIO_LEN} chars)")
        for seat, p in enumerate(self.players):
            if p is None:
                player = Player(
                    player_id=f"p_{secrets.token_hex(4)}",
                    name=name or f"player-{seat}",
                    seat=seat,
                    token=f"tok_{secrets.token_urlsafe(12)}",
                    bio=bio,
                )
                self.players[seat] = player
                self._token_to_seat[player.token] = seat
                if self.owner_seat < 0:
                    self.owner_seat = seat
                if all(p is not None for p in self.players):
                    self._deal()
                self.last_active = time.time()
                return player
        raise GameError("game is full")

    def seat_of(self, token: str) -> int:
        if token not in self._token_to_seat:
            raise GameError("invalid token")
        return self._token_to_seat[token]

    # ---- chat -----------------------------------------------------------

    MAX_CHAT_LEN = 500
    CHAT_HISTORY_LIMIT = 200
    MAX_BIO_LEN = 1000

    def post_chat(self, token: str, text: str) -> ChatMessage:
        seat = self.seat_of(token)
        text = (text or "").strip()
        if not text:
            raise GameError("empty message")
        if len(text) > self.MAX_CHAT_LEN:
            raise GameError(f"message too long (>{self.MAX_CHAT_LEN} chars)")
        msg = ChatMessage(
            seat=seat,
            name=self.players[seat].name,
            text=text,
            timestamp=time.time(),
        )
        self.chat.append(msg)
        if len(self.chat) > self.CHAT_HISTORY_LIMIT:
            self.chat = self.chat[-self.CHAT_HISTORY_LIMIT :]
        self.last_active = time.time()
        return msg

    def chat_since(self, since_ts: float = 0.0, limit: int = 50) -> List[ChatMessage]:
        msgs = [m for m in self.chat if m.timestamp > since_ts]
        return msgs[-limit:]

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
        self.turn_started_at = time.time()

    def bid(self, token: str, value: int) -> None:
        self._check_turn_timeout()
        if self.phase != Phase.BIDDING:
            raise GameError("not in bidding phase")
        seat = self.seat_of(token)
        if seat != self.bid_turn:
            raise GameError("not your turn to bid")
        if not self._timeout_auto:
            elapsed = time.time() - self.turn_started_at
            if elapsed < self.THINK_SECONDS:
                remaining = self.THINK_SECONDS - elapsed
                raise GameError(
                    f"thinking phase: must wait {remaining:.1f}s more (action window opens at t={self.THINK_SECONDS:.0f}s)"
                )
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
        self.turn_started_at = time.time()
        self.last_active = time.time()

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
        self.turn_started_at = time.time()
        self.last_active = time.time()

    # ---- play -----------------------------------------------------------

    def play(self, token: str, card_codes: Sequence[str]) -> dict:
        self._check_turn_timeout()
        self.last_active = time.time()
        if self.phase != Phase.PLAYING:
            raise GameError("not in playing phase")
        seat = self.seat_of(token)
        if seat != self.current_turn:
            raise GameError("not your turn")
        if not self._timeout_auto:
            elapsed = time.time() - self.turn_started_at
            if elapsed < self.THINK_SECONDS:
                remaining = self.THINK_SECONDS - elapsed
                raise GameError(
                    f"thinking phase: must wait {remaining:.1f}s more (action window opens at t={self.THINK_SECONDS:.0f}s)"
                )

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
        self.turn_started_at = time.time()
        # if both opponents passed, leader keeps leading (handled implicitly:
        # after 2 passes, next player == last_play_seat — they then "lead" a new trick)
        if nxt == self.last_play_seat:
            # new trick: clear table
            self.last_pattern = None
            # last_play_seat stays = leader; play() treats leading correctly
            # since seat == last_play_seat is allowed to play anything.
        self.current_turn = nxt

    # ---- disband -------------------------------------------------------

    def disband(self, reason: str = "owner disbanded") -> None:
        self.phase = Phase.FINISHED
        self.disbanded = True
        self.disbanded_reason = reason
        self.turn_started_at = 0.0

    def leave_seat(self, token: str) -> dict:
        """A seated player gives up their seat.

        Rules:
          - If the leaver is the owner, the whole room is disbanded.
          - Otherwise, leaving is only allowed in WAITING or FINISHED phase.
        Returns a dict with ``disbanded`` and ``seat`` fields.
        """
        seat = self.seat_of(token)
        is_owner = (seat == self.owner_seat)
        if is_owner:
            self.disband("owner left seat")
            return {"disbanded": True, "seat": seat, "owner": True}
        if self.phase in (Phase.BIDDING, Phase.PLAYING):
            raise GameError("game in progress, cannot leave seat (ask owner to disband)")
        p = self.players[seat]
        if p is not None:
            self._token_to_seat.pop(p.token, None)
        self.players[seat] = None
        self.last_active = time.time()
        return {"disbanded": False, "seat": seat, "owner": False}

    def restart(self) -> None:
        """Start a new round in the same room with the same seated players.

        Only allowed when the previous round has finished (and the room
        was not disbanded). Resets all per-round state and re-deals.
        Player identities, tokens, chat history, owner, and spectator
        token are preserved.
        """
        if self.disbanded:
            raise GameError("room has been disbanded")
        self.last_active = time.time()
        if self.phase != Phase.FINISHED:
            raise GameError("current round is not finished yet")
        if any(p is None for p in self.players):
            raise GameError("need 3 seated players to restart")
        # reset per-round state
        for p in self.players:
            if p is not None:
                p.hand = []
                p.is_landlord = False
        self.bottom_cards = []
        self.bids = [-1, -1, -1]
        self.current_bid = 0
        self.landlord_seat = -1
        self.bid_turn = -1
        self.current_turn = -1
        self.last_play_seat = -1
        self.last_pattern = None
        self.history = []
        self.winner_seat = -1
        self.turn_started_at = 0.0
        self._timeout_auto = False
        self.phase = Phase.WAITING
        self._deal()

    def is_owner(self, token: str) -> bool:
        try:
            return self.seat_of(token) == self.owner_seat
        except GameError:
            return False

    # ---- turn clock -----------------------------------------------------

    def _check_turn_timeout(self) -> None:
        """If the current actor missed the 20s window, auto-resolve."""
        if self.phase not in (Phase.BIDDING, Phase.PLAYING):
            return
        if self.turn_started_at <= 0 or self._timeout_auto:
            return
        elapsed = time.time() - self.turn_started_at
        if elapsed < self.TURN_TOTAL_SECONDS:
            return
        self._timeout_auto = True
        try:
            if self.phase == Phase.BIDDING:
                seat = self.bid_turn
                if seat < 0 or self.players[seat] is None:
                    return
                self.bid(self.players[seat].token, 0)
            elif self.phase == Phase.PLAYING:
                seat = self.current_turn
                if seat < 0 or self.players[seat] is None:
                    return
                token = self.players[seat].token
                if self.last_play_seat == -1 or self.last_play_seat == seat:
                    # leader cannot pass: auto-play smallest single
                    hand = self.players[seat].hand
                    if not hand:
                        return
                    smallest = min(hand, key=lambda c: (c.rank_value, c.suit))
                    self.play(token, [smallest.code])
                else:
                    self.play(token, [])
        finally:
            self._timeout_auto = False
        # After one auto-resolution the clock has been reset by the recursive
        # bid/play; recurse once more in case multiple turns expired between
        # observations (e.g. nobody polled for 60s).
        if self.phase in (Phase.BIDDING, Phase.PLAYING):
            elapsed2 = time.time() - self.turn_started_at
            if elapsed2 >= self.TURN_TOTAL_SECONDS:
                self._check_turn_timeout()

    def _turn_clock_info(self) -> dict:
        if self.phase not in (Phase.BIDDING, Phase.PLAYING) or self.turn_started_at <= 0:
            return {
                "turn_started_at": 0,
                "elapsed": 0,
                "thinking_remaining": 0,
                "action_remaining": 0,
                "can_act": False,
                "think_seconds": self.THINK_SECONDS,
                "action_seconds": self.ACTION_SECONDS,
                "total_seconds": self.TURN_TOTAL_SECONDS,
            }
        elapsed = max(0.0, time.time() - self.turn_started_at)
        thinking_remaining = max(0.0, self.THINK_SECONDS - elapsed)
        action_remaining = max(0.0, self.TURN_TOTAL_SECONDS - elapsed)
        return {
            "turn_started_at": self.turn_started_at,
            "elapsed": round(elapsed, 3),
            "thinking_remaining": round(thinking_remaining, 3),
            "action_remaining": round(action_remaining, 3),
            "can_act": thinking_remaining <= 0 and action_remaining > 0,
            "think_seconds": self.THINK_SECONDS,
            "action_seconds": self.ACTION_SECONDS,
            "total_seconds": self.TURN_TOTAL_SECONDS,
        }

    # ---- introspection --------------------------------------------------

    def compute_settlement(self) -> Dict[int, int]:
        """Per-seat point delta for the just-finished round; {} if not applicable."""
        if self.phase != Phase.FINISHED or self.winner_seat < 0 or self.landlord_seat < 0:
            return {}
        ll = self.landlord_seat
        winner = self.winner_seat
        if winner == ll:
            return {s: (20 if s == ll else -10) for s in range(3)}
        return {s: (-20 if s == ll else 10) for s in range(3)}

    def public_state(self) -> dict:
        self._check_turn_timeout()
        return {
            "game_id": self.game_id,
            "name": self.name,
            "description": self.description,
            "phase": self.phase.value,
            "rule_mode": self.rule_mode,
            "players": [
                {
                    "seat": i,
                    "name": p.name if p else None,
                    "joined": p is not None,
                    "hand_count": len(p.hand) if p else 0,
                    "is_landlord": p.is_landlord if p else False,
                    "bio": p.bio if p else "",
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
            "owner_seat": self.owner_seat,
            "disbanded": self.disbanded,
            "disbanded_reason": self.disbanded_reason,
            "chat": [
                {
                    "seat": m.seat,
                    "name": m.name,
                    "text": m.text,
                    "timestamp": m.timestamp,
                }
                for m in self.chat[-50:]
            ],
            "turn_clock": self._turn_clock_info(),
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

    def omniscient_state(self) -> dict:
        """All-hands view for spectator-token holders."""
        state = self.public_state()
        for i, p in enumerate(self.players):
            if p is not None:
                state["players"][i]["hand"] = [c.code for c in p.hand]
        state["omniscient"] = True
        return state

    def is_spectator_token(self, token: str) -> bool:
        return bool(token) and token == self.spectator_token
