from __future__ import annotations
from dataclasses import dataclass, field
import random
from typing import List, Any, Callable


@dataclass
class Card:
    id: str
    name: str
    data: dict = field(default_factory=dict)


class Deck:
    def __init__(self, cards: List[Card] | None = None):
        self.cards: List[Card] = list(cards) if cards else []

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def draw(self, n: int = 1) -> List[Card]:
        drawn: List[Card] = []
        for _ in range(n):
            if not self.cards:
                break
            drawn.append(self.cards.pop(0))
        return drawn

    def add(self, card: Card) -> None:
        self.cards.append(card)

    def count(self) -> int:
        return len(self.cards)


class Player:
    UNIQUE_DAMAGE_ABILITIES = frozenset({"piercing_strike", "guard_breaker", "siphon"})

    def __init__(self, name: str, deck: Deck | None = None):
        self.name = name
        self.deck = deck if deck else Deck()
        self.hand: List[Card] = []
        self.discard: List[Card] = []
        self.hp: int = 20
        self.armor: int = 0

    def draw(self, n: int = 1) -> List[Card]:
        cards = self.deck.draw(n)
        self.hand.extend(cards)
        return cards

    def hand_size(self) -> int:
        return len(self.hand)

    def receive_damage(self, amount: int, ignore_armor: bool = False) -> int:
        amount = max(0, amount)

        if not ignore_armor and self.armor > 0:
            absorbed = min(self.armor, amount)
            self.armor -= absorbed
            amount -= absorbed

        if amount > 0:
            self.hp = max(0, self.hp - amount)
        return amount

    def heal(self, amount: int) -> int:
        amount = max(0, amount)
        self.hp += amount
        return amount

    def _require_opponent(self, opponent: Player | None, effect_name: str) -> Player:
        if opponent is None:
            raise ValueError(f"{effect_name} effect requires an opponent")
        return opponent

    def _resolve_unique_ability(self, card: Card, opponent: Player | None) -> None:
        ability = card.data.get("ability")
        if ability is None:
            return

        if callable(ability):
            ability(self, opponent, card)
            return

        if not isinstance(ability, str):
            raise ValueError("Card ability must be a string or callable")

        if ability == "piercing_strike":
            target = self._require_opponent(opponent, "piercing_strike")
            damage = int(card.data.get("damage", 0))
            target.receive_damage(damage, ignore_armor=True)
            return

        if ability == "guard_breaker":
            target = self._require_opponent(opponent, "guard_breaker")
            target.armor = 0
            damage = int(card.data.get("damage", 0))
            target.receive_damage(damage)
            return

        if ability == "siphon":
            target = self._require_opponent(opponent, "siphon")
            damage = int(card.data.get("damage", 0))
            dealt = target.receive_damage(damage)
            self.heal(dealt)
            return

        raise ValueError(f"Unknown unique ability: {ability}")

    def resolve_card_effect(self, card: Card, opponent: Player | None = None) -> None:
        if not isinstance(card.data, dict):
            return

        if "armor" in card.data:
            self.armor += max(0, int(card.data["armor"]))

        if "draw" in card.data:
            self.draw(max(0, int(card.data["draw"])))

        if "heal" in card.data:
            self.heal(int(card.data["heal"]))

        ability = card.data.get("ability")
        # Callable abilities can opt out of base damage application by setting
        # `ability_handles_damage=True` in card.data when they apply damage internally.
        ability_handles_damage = (
            isinstance(ability, str) and ability in Player.UNIQUE_DAMAGE_ABILITIES
        ) or (
            callable(ability) and bool(card.data.get("ability_handles_damage", False))
        )

        if "damage" in card.data and not ability_handles_damage:
            target = self._require_opponent(opponent, "damage")
            target.receive_damage(int(card.data["damage"]))

        if "self_damage" in card.data:
            self.receive_damage(int(card.data["self_damage"]))

        self._resolve_unique_ability(card, opponent)

    def play_card(self, card: Card, opponent: Player | None = None) -> Card:
        """Play a card from hand: remove from hand and place into discard. Returns the card.

        This prototype resolves effects directly from card data.
        """
        if card not in self.hand:
            raise ValueError("Card not in hand")
        # remove from hand
        self.hand.remove(card)
        # add to discard
        self.discard.append(card)
        self.resolve_card_effect(card, opponent=opponent)
        return card


class TurnManager:
    PHASES = ['start', 'main', 'resolve', 'end']

    def __init__(self, players: List[Player]):
        if not players:
            raise ValueError("TurnManager requires at least one player")
        self.players = players
        self.active_index = 0
        self.active_player = self.players[self.active_index]
        self.phase: str | None = None
        self.turn_number = 0

    def start_turn(self) -> None:
        self.turn_number += 1
        self.phase = 'start'
        # default start-of-turn effects: active player draws 1 card
        if hasattr(self, 'active_player') and getattr(self.active_player, 'draw', None):
            try:
                self.active_player.draw(1)
            except Exception:
                # drawing should not break turn management; swallow errors in prototype
                pass

    def advance_phase(self) -> None:
        if self.phase is None:
            self.start_turn()
            return

        try:
            idx = TurnManager.PHASES.index(self.phase)
        except ValueError:
            self.phase = 'start'
            return

        next_idx = idx + 1
        if next_idx < len(TurnManager.PHASES):
            self.phase = TurnManager.PHASES[next_idx]
        else:
            # finished end phase; rotate to next player and start new turn
            self.end_turn()

    def end_turn(self) -> None:
        # move to next player
        self.active_index = (self.active_index + 1) % len(self.players)
        self.active_player = self.players[self.active_index]
        # start the next player's turn automatically
        self.start_turn()
