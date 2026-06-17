from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ShopCard:
    name: str
    cost: int
    damage: int


CATALOG: Tuple[ShopCard, ...] = (
    ShopCard(name="Dagger", cost=1, damage=1),
    ShopCard(name="Strike", cost=2, damage=2),
    ShopCard(name="Power Slash", cost=3, damage=3),
    ShopCard(name="Heavy Blow", cost=4, damage=4),
)


class SimulatedAIPlayer:
    def __init__(self, hp: int = 20):
        self.hp = hp
        self.resources = 0
        self.deck: List[int] = [1, 1, 1, 1, 1]
        self.discard: List[int] = []

    def draw_attack(self, rng: random.Random) -> int:
        if not self.deck:
            if not self.discard:
                return 0
            rng.shuffle(self.discard)
            self.deck = self.discard
            self.discard = []
        return self.deck.pop(0)

    def choose_purchase(self, rng: random.Random) -> ShopCard | None:
        affordable = [card for card in CATALOG if card.cost <= self.resources]
        if not affordable:
            return None
        best_damage = max(card.damage for card in affordable)
        best_options = [card for card in affordable if card.damage == best_damage]
        return rng.choice(best_options)

    def buy_card(self, card: ShopCard) -> None:
        self.resources -= card.cost
        self.discard.append(card.damage)


def run_single_game(rng: random.Random, max_turns: int = 60) -> Tuple[int, Counter]:
    p1 = SimulatedAIPlayer()
    p2 = SimulatedAIPlayer()
    purchases: Counter = Counter()
    turn_count = 0
    active, opponent = p1, p2

    while p1.hp > 0 and p2.hp > 0 and turn_count < max_turns:
        turn_count += 1
        active.resources = min(10, active.resources + 1)

        attack = active.draw_attack(rng)
        opponent.hp -= attack

        card = active.choose_purchase(rng)
        if card:
            active.buy_card(card)
            purchases[card.name] += 1

        active, opponent = opponent, active

    return turn_count, purchases


def generate_report(
    num_games: int = 1000,
    seed: int = 42,
    top_n: int = 3,
) -> Dict[str, object]:
    rng = random.Random(seed)
    game_lengths: List[int] = []
    total_purchases: Counter = Counter()

    for _ in range(num_games):
        game_length, purchases = run_single_game(rng=rng)
        game_lengths.append(game_length)
        total_purchases.update(purchases)

    average_game_length = sum(game_lengths) / len(game_lengths) if game_lengths else 0.0

    return {
        "num_games": num_games,
        "average_game_length": average_game_length,
        "most_purchased_cards": total_purchases.most_common(top_n),
        "all_purchase_counts": dict(total_purchases),
    }
