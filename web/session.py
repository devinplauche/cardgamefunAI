from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import random
import time
import uuid
from typing import Any

from hero_engine import (
    HRCard,
    HRMarket,
    HRPlayer,
    auto_expend_all,
    buy_card,
    expend_champion,
    has_ally,
    load_hero_cards,
    play_card,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = REPO_ROOT / "data" / "hero_realms_cards.json"
DEFAULT_CARDS = load_hero_cards(str(CARDS_PATH))
PHASES = ("play", "champion", "buy", "combat")


def _card_view(card: HRCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "cost": card.cost,
        "faction": card.faction,
        "cardType": card.card_type,
        "guard": card.guard,
        "health": card.health,
        "effects": card.effects,
        "text": card.text,
    }


def _champion_view(champion) -> dict[str, Any]:
    base = _card_view(champion.card)
    base.update(
        {
            "currentHealth": champion.current_health,
            "exhausted": champion.exhausted,
            "alive": champion.alive,
        }
    )
    return base


def _player_view(player: HRPlayer, reveal_hand: bool) -> dict[str, Any]:
    return {
        "name": player.name,
        "hp": player.hp,
        "gold": player.gold,
        "combat": player.combat,
        "deckCount": len(player.deck),
        "handCount": len(player.hand),
        "discardCount": len(player.discard),
        "banishCount": len(player.banish),
        "nextBuyToHand": player.next_buy_to_hand,
        "nextBuyToTop": player.next_buy_to_top,
        "nextBuyToTopActionOnly": player.next_buy_to_top_action_only,
        "hand": [_card_view(card) for card in player.hand] if reveal_hand else [],
        "board": [_champion_view(champion) for champion in player.board if champion.alive],
    }


def _market_view(market: HRMarket) -> dict[str, Any]:
    return {
        "row": [_card_view(card) if card else None for card in market.row_cards()],
        "fireGemsRemaining": market.fire_gems_remaining,
    }


@dataclass
class GameSession:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    seed: int | None = None
    algorithm: str = "mcts"
    budget_ms: int = 60
    cards: list[HRCard] = field(default_factory=lambda: list(DEFAULT_CARDS))
    player: HRPlayer = field(init=False)
    bot: HRPlayer = field(init=False)
    market: HRMarket = field(init=False)
    turn_number: int = field(default=1)
    active_player: str = field(default="player")
    phase: str = field(default="play")
    winner: str | None = field(default=None)
    log: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    last_bot_insight: dict[str, Any] | None = field(default=None)
    record_history: bool = field(default=True)

    def __post_init__(self) -> None:
        if self.seed is not None:
            random.seed(self.seed)
        self.player = HRPlayer("Player")
        self.bot = HRPlayer("Bot")
        self.player.setup_starting_deck()
        self.bot.setup_starting_deck()
        self.player.draw(3)
        self.bot.draw(5)
        self.market = HRMarket(self.cards)
        self._start_turn(self.player)
        self.record_event("system", "Game created")

    def clone(self) -> "GameSession":
        # history/log are presentation-only, and each history entry holds a full
        # state snapshot. Deep-copying them dominated the MCTS search loop (8 ms
        # per clone against a 60 ms budget, ~9 iterations per decision), so they
        # are detached for simulation clones.
        saved = (self.history, self.log, self.last_bot_insight)
        self.history, self.log, self.last_bot_insight = [], [], None
        try:
            copy = deepcopy(self)
        finally:
            self.history, self.log, self.last_bot_insight = saved
        copy.record_history = False
        return copy

    def _start_turn(self, player: HRPlayer) -> None:
        player.gold = 0
        player.combat = 0
        player.actions_played = 0
        player.cards_bought = 0
        player.next_buy_to_hand = False
        player.next_buy_to_top = False
        player.next_buy_to_top_action_only = False
        for champion in player.board:
            champion.exhausted = False

    def _current(self) -> HRPlayer:
        return self.player if self.active_player == "player" else self.bot

    def _opponent(self) -> HRPlayer:
        return self.bot if self.active_player == "player" else self.player

    def _check_winner(self) -> None:
        if self.player.hp <= 0 and self.bot.hp <= 0:
            self.winner = "draw"
        elif self.player.hp <= 0:
            self.winner = "bot"
        elif self.bot.hp <= 0:
            self.winner = "player"

    def log_event(self, message: str, kind: str = "system", bot_insight: dict[str, Any] | None = None) -> None:
        self.log.append(
            {
                "kind": kind,
                "message": message,
                "turn": self.turn_number,
                "phase": self.phase,
                "activePlayer": self.active_player,
                "at": round(time.time(), 3),
                "botInsight": bot_insight,
            }
        )
        self.log = self.log[-50:]

    def _core_state(self) -> dict[str, Any]:
        self._check_winner()
        return {
            "sessionId": self.session_id,
            "turnNumber": self.turn_number,
            "phase": self.phase,
            "activePlayer": self.active_player,
            "winner": self.winner,
            "player": _player_view(self.player, reveal_hand=True),
            "bot": _player_view(self.bot, reveal_hand=False),
            "market": _market_view(self.market),
            "legalActions": self.legal_actions(),
            "log": self.log[-20:],
            "botInsight": self.last_bot_insight,
        }

    def record_event(self, kind: str, label: str, bot_insight: dict[str, Any] | None = None) -> None:
        # Simulation clones skip this entirely: every call serialises a full
        # state snapshot, which is pure overhead inside an MCTS rollout.
        if not self.record_history:
            return
        insight = bot_insight if bot_insight is not None else self.last_bot_insight
        self.log_event(label, kind, bot_insight=insight)
        self.history.append(
            {
                "id": f"{self.turn_number}-{len(self.history) + 1}",
                "kind": kind,
                "label": label,
                "turn": self.turn_number,
                "phase": self.phase,
                "activePlayer": self.active_player,
                "botInsight": insight,
                "state": self._core_state(),
            }
        )
        self.history = self.history[-80:]

    def legal_actions(self) -> list[dict[str, Any]]:
        if self.winner:
            return []

        player = self._current()
        opponent = self._opponent()
        actions: list[dict[str, Any]] = []

        if self.phase == "play":
            for card in player.hand:
                actions.append(
                    {
                        "type": "play_card",
                        "cardId": card.id,
                        "label": card.name,
                        "priority": card.cost + card.get("draw", 0) * 3 + card.get("gold", 0) * 2 + card.get("combat", 0),
                    }
                )
        elif self.phase == "champion":
            for champion in player.board:
                if champion.alive and not champion.exhausted:
                    actions.append(
                        {
                            "type": "expend_champion",
                            "championId": champion.card.id,
                            "label": champion.card.name,
                            "priority": champion.card.cost + champion.card.health,
                        }
                    )
        elif self.phase == "buy":
            for idx, card in enumerate(self.market.row_cards()):
                if card and card.cost <= player.gold:
                    actions.append(
                        {
                            "type": "buy_card",
                            "marketIndex": idx,
                            "label": card.name,
                            "priority": card.cost + card.get("combat", 0) * 2 + card.get("gold", 0) * 2 + card.get("draw", 0) * 2,
                        }
                    )
            if player.gold >= 2 and self.market.can_buy_fire_gem():
                actions.append(
                    {
                        "type": "buy_card",
                        "marketIndex": 5,
                        "label": "Fire Gem",
                        "priority": 6,
                    }
                )
        elif self.phase == "combat":
            guards = [champion for champion in opponent.board if champion.guard and champion.alive]
            # Combat can only be assigned if there is combat to assign. Offering
            # guard targets at 0 combat made attack_target_action raise.
            if player.combat > 0:
                if guards:
                    for champion in guards:
                        actions.append(
                            {
                                "type": "attack_target",
                                "target": "champion",
                                "championId": champion.card.id,
                                "label": champion.card.name,
                                "priority": 10 - champion.current_health,
                            }
                        )
                else:
                    actions.append(
                        {
                            "type": "attack_target",
                            "target": "player",
                            "label": opponent.name,
                            "priority": player.combat,
                        }
                    )

        actions.append({"type": "advance_phase", "label": "Next Phase", "priority": -10})
        return sorted(actions, key=lambda item: item.get("priority", 0), reverse=True)

    def play_card(self, card_id: str) -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase != "play":
            raise ValueError("Cards can only be played during the play phase")
        card = next((item for item in player.hand if item.id == card_id), None)
        if card is None:
            raise ValueError("Card not found in hand")

        play_card(player, card, self.market, ally_bonus=has_ally(card, player), opponent=opponent)
        self.record_event("play", f"Played {card.name}")
        self._check_winner()
        return self.get_state()

    def expend_champion_action(self, champion_id: str) -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase != "champion":
            raise ValueError("Champions can only be expended during the champion phase")
        champion = next((item for item in player.board if item.card.id == champion_id), None)
        if champion is None:
            raise ValueError("Champion not found")
        if not expend_champion(player, champion, opponent):
            raise ValueError("Champion could not be expended")

        self.record_event("expend", f"Expended {champion.card.name}")
        self._check_winner()
        return self.get_state()

    def buy_card_action(self, market_index: int) -> dict[str, Any]:
        player = self._current()
        if self.phase != "buy":
            raise ValueError("Cards can only be bought during the buy phase")
        label = "Fire Gem"
        if market_index != 5:
            current_card = self.market.row_cards()[market_index]
            label = current_card.name if current_card else "Market card"

        if buy_card(player, self.market, market_index):
            self.record_event("buy", f"Bought {label}")
        else:
            raise ValueError("Purchase failed")

        self._check_winner()
        return self.get_state()

    def attack_target_action(self, target_kind: str, champion_id: str | None = None) -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase != "combat":
            raise ValueError("Combat attacks can only happen during the combat phase")
        if player.combat <= 0:
            raise ValueError("No combat remaining")

        guards = [champion for champion in opponent.board if champion.guard and champion.alive]
        if target_kind == "player":
            if guards:
                raise ValueError("Guards must be attacked before the player")
            dealt = player.combat
            opponent.hp -= dealt
            player.combat = 0
            self.record_event("combat", f"Dealt {dealt} combat to {opponent.name}")
            self._check_winner()
            return self.get_state()

        champion = next((item for item in guards if item.card.id == champion_id), None)
        if champion is None:
            raise ValueError("Guard champion not found")

        dealt = min(player.combat, champion.current_health)
        champion.current_health -= dealt
        player.combat -= dealt
        if not champion.alive:
            opponent.board = [item for item in opponent.board if item.alive]
        self.record_event("combat", f"Assigned {dealt} combat to {champion.card.name}")

        if player.combat > 0 and not any(item.guard and item.alive for item in opponent.board):
            spill = player.combat
            opponent.hp -= spill
            player.combat = 0
            self.record_event("combat", f"Spilled {spill} combat to {opponent.name}")

        self._check_winner()
        return self.get_state()

    def advance_phase(self) -> dict[str, Any]:
        if self.winner:
            return self.get_state()

        current = self.phase
        if current == "play":
            self.phase = "champion"
        elif current == "champion":
            self.phase = "buy"
        elif current == "buy":
            self.phase = "combat"
        elif current == "combat":
            self.end_turn()
            return self.get_state()
        else:
            raise ValueError("Unknown phase")

        self.record_event("phase", f"Advanced to {self.phase} phase")
        return self.get_state()

    def end_turn(self) -> dict[str, Any]:
        if self.winner:
            return self.get_state()

        current = self._current()
        for card in list(current.hand):
            current.discard.append(card)
        current.hand.clear()
        current.draw(5)

        self.active_player = "bot" if self.active_player == "player" else "player"
        self.turn_number += 1
        self.phase = "play"
        self._start_turn(self._current())
        self.record_event("turn", f"{current.name} ended turn")
        self.record_event("turn", f"{self._current().name} started turn")
        self._check_winner()
        return self.get_state()

    def run_bot_turn(self) -> dict[str, Any]:
        from web.bot import run_bot_turn

        if self.active_player != "bot" or self.winner:
            return self.get_state()
        insight = run_bot_turn(self, budget_ms=self.budget_ms, algorithm=self.algorithm)
        self.last_bot_insight = insight
        self._check_winner()
        return self.get_state()

    def get_state(self) -> dict[str, Any]:
        state = self._core_state()
        state["history"] = self.history[-40:]
        return state


def create_session(seed: int | None = None, algorithm: str = "mcts", budget_ms: int = 60) -> GameSession:
    return GameSession(seed=seed, algorithm=algorithm, budget_ms=budget_ms)
