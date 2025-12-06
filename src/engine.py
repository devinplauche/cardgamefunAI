from __future__ import annotations
from dataclasses import dataclass, field
import random
from typing import List, Any


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
    def __init__(self, name: str, deck: Deck | None = None):
        self.name = name
        self.deck = deck if deck else Deck()
        self.hand: List[Card] = []
        self.discard: List[Card] = []
        self.hp: int = 20

    def draw(self, n: int = 1) -> List[Card]:
        cards = self.deck.draw(n)
        self.hand.extend(cards)
        return cards

    def hand_size(self) -> int:
        return len(self.hand)

    def play_card(self, card: Card) -> Card:
        """Play a card from hand: remove from hand and place into discard. Returns the card.

        This is a simple prototype behavior: no cost checks or effect resolution here.
        """
        if card not in self.hand:
            raise ValueError("Card not in hand")
        # remove from hand
        self.hand.remove(card)
        # add to discard
        self.discard.append(card)
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

