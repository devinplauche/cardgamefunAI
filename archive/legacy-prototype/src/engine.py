from __future__ import annotations
from dataclasses import dataclass, field
import random
from typing import List, Any
import json
import os


@dataclass
class Card:
    id: str
    name: str
    data: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> 'Card':
        return Card(id=d.get('id', ''), name=d.get('name', ''), data=d.get('data', {}))


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


def load_cards_from_file(path: str) -> List[Card]:
    """Load card definitions from a JSON file and return a list of Card objects."""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    cards: List[Card] = []
    for d in data:
        cards.append(Card.from_dict(d))
    return cards


class Player:
    def __init__(self, name: str, deck: Deck | None = None):
        self.name = name
        self.deck = deck if deck else Deck()
        self.hand: List[Card] = []
        self.discard: List[Card] = []
        self.hp: int = 20
        self.armor: int = 0

    def draw(self, n: int = 1) -> List[Card]:
        drawn: List[Card] = []
        remaining = n
        # attempt to draw, reshuffling discard into deck if necessary
        while remaining > 0:
            cards = self.deck.draw(remaining)
            if cards:
                drawn.extend(cards)
                remaining -= len(cards)
            else:
                # no cards in deck; if discard exists, reshuffle it into deck
                if self.discard:
                    self.shuffle_discard_into_deck()
                    continue
                # nothing left to draw
                break

        self.hand.extend(drawn)
        return drawn

    def shuffle_discard_into_deck(self) -> None:
        """Move discard pile back into deck and shuffle."""
        if not self.discard:
            return
        # move discard to deck
        for c in self.discard:
            self.deck.add(c)
        self.discard.clear()
        self.deck.shuffle()

    def hand_size(self) -> int:
        return len(self.hand)

    def play_card(self, card: Card, target: 'Player' | None = None) -> Card:
        """Play a card from hand: remove from hand and place into discard. Returns the card.

        If `target` is provided and the card has effects (e.g., `data['damage']`),
        apply them immediately. This is a simple prototype resolution path.
        """
        if card not in self.hand:
            raise ValueError("Card not in hand")
        self.hand.remove(card)

        if isinstance(card.data, dict):
            self._apply_effects(card.data, self, target)

        self.discard.append(card)
        return card

    def _apply_effects(self, data: dict, owner: 'Player', target: 'Player' | None) -> None:
        dmg = data.get('damage')
        if isinstance(dmg, (int, float)) and target is not None:
            actual = int(dmg)
            if target.armor > 0:
                absorbed = min(target.armor, actual)
                target.armor -= absorbed
                actual -= absorbed
            target.hp -= actual

        heal = data.get('heal')
        if isinstance(heal, (int, float)):
            owner.hp += int(heal)

        self_dmg = data.get('self_damage')
        if isinstance(self_dmg, (int, float)):
            owner.hp -= int(self_dmg)

        armor_gain = data.get('armor_gain')
        if isinstance(armor_gain, (int, float)):
            owner.armor += int(armor_gain)

        draws = data.get('draw')
        if isinstance(draws, int) and draws > 0:
            owner.draw(draws)


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


class Game:
    """High-level game controller: holds players, a turn manager, a play stack, and a play area.

    play_stack: list of dict entries {'card', 'owner', 'target'} resolved in LIFO order
    play_area: list of entries currently displayed on the table (before resolution)
    """

    def __init__(self, players: List[Player]):
        self.players = players
        self.turn_manager = TurnManager(players)
        self.play_stack: List[dict] = []
        self.play_area: List[dict] = []

    def play_card(self, player: Player, card: Card, target: Player | None = None) -> None:
        """Player plays a card: remove from hand and place onto play_area and stack (to be resolved).

        Does NOT immediately apply effects; resolution happens in `resolve_stack`.
        """
        if card not in player.hand:
            raise ValueError("Card not in hand")
        # remove from hand
        player.hand.remove(card)
        entry = {'card': card, 'owner': player, 'target': target}
        # put onto play area and stack
        self.play_area.append(entry)
        self.play_stack.append(entry)

    def resolve_stack(self) -> None:
        """Resolve all effects on the stack in LIFO order and move cards to their owner's discard."""
        while self.play_stack:
            entry = self.play_stack.pop()  # LIFO
            card = entry.get('card')
            owner = entry.get('owner')
            target = entry.get('target')

            if isinstance(card.data, dict):
                owner._apply_effects(card.data, owner, target)

            try:
                self.play_area.remove(entry)
            except ValueError:
                pass
            owner.discard.append(card)

    def run_round(self, ai_strategy=None) -> None:
        """Run a simple automated round: active player -> next player.

        If `ai_strategy` is provided (a class with `take_turn(player, opponent)` static method),
        the active player will use it to choose and play a card.
        Falls back to AggressiveAI if not specified.
        """
        tm = self.turn_manager
        tm.start_turn()

        active = tm.active_player
        target = next(p for p in self.players if p is not active)

        if ai_strategy is not None:
            try:
                ai_strategy.take_turn(active, target)
            except Exception:
                pass

        tm.phase = 'resolve'
        self.resolve_stack()

        tm.advance_phase()

