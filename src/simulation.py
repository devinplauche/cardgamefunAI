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
    bonus_resources: int = 0


CATALOG: Tuple[ShopCard, ...] = (
    ShopCard(name="Profit", cost=1, damage=0, bonus_resources=2),
    ShopCard(name="Spark", cost=1, damage=1, bonus_resources=0),
    ShopCard(name="Flare", cost=2, damage=2, bonus_resources=0),
    ShopCard(name="Surge", cost=3, damage=3, bonus_resources=1),
    ShopCard(name="Nova", cost=4, damage=5, bonus_resources=0),
)

STARTING_ATTACK_DAMAGE = 1
STARTING_DECK_SIZE = 5
SAVE_RESOURCES_PROBABILITY = 0.1
MAX_RESOURCES = 10


class SimulatedAIPlayer:
    def __init__(self, hp: int = 20):
        self.hp = hp
        self.resources = 0
        self.deck: List[int] = [STARTING_ATTACK_DAMAGE] * STARTING_DECK_SIZE
        self.discard: List[int] = []

    def draw_attack(self, rng: random.Random) -> int:
        if not self.deck:
            if not self.discard:
                return 0
            rng.shuffle(self.discard)
            self.deck = self.discard[:]
            self.discard = []
        return self.deck.pop(0)

    def choose_purchase(self, rng: random.Random) -> ShopCard | None:
        affordable = [card for card in CATALOG if card.cost <= self.resources]
        if not affordable:
            return None
        # Occasionally save resources for stronger future buys.
        if rng.random() < SAVE_RESOURCES_PROBABILITY:
            return None
        weights = [
            ((card.damage + (card.bonus_resources * 1.5) + 0.5) / card.cost) ** 2
            for card in affordable
        ]
        return rng.choices(affordable, weights=weights, k=1)[0]

    def buy_card(self, card: ShopCard) -> None:
        self.resources -= card.cost
        self.resources = min(MAX_RESOURCES, self.resources + card.bonus_resources)
        if card.damage > 0:
            self.discard.append(card.damage)


def run_single_game(rng: random.Random, max_actions: int = 60) -> Tuple[int, Counter]:
    """Run one AI-vs-AI game.

    `max_actions` is the maximum number of player actions before forcing game end.

    Returns a tuple of `(turn_count, purchases_counter)` where `turn_count` is
    the number of actions taken before game end and `purchases_counter` maps
    purchased card names to the number of purchases in this game.
    """
    p1 = SimulatedAIPlayer()
    p2 = SimulatedAIPlayer()
    purchases: Counter = Counter()
    turn_count = 0
    active, opponent = p1, p2

    while p1.hp > 0 and p2.hp > 0 and turn_count < max_actions:
        turn_count += 1
        active.resources = min(MAX_RESOURCES, active.resources + 1)

        attack = active.draw_attack(rng)
        if attack > 0:
            active.discard.append(attack)
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
    """Generate aggregate purchase and game-length metrics from simulations.

    Returns a dictionary with:
    - `num_games`: number of games simulated.
    - `average_game_length`: average actions per game.
    - `most_purchased_cards`: top purchased cards as `(name, count)` tuples.
    - `all_purchase_counts`: full card purchase frequency map.
    """
    if num_games <= 0:
        raise ValueError("num_games must be greater than 0")

    rng = random.Random(seed)
    game_lengths: List[int] = []
    total_purchases: Counter = Counter()

    for _ in range(num_games):
        game_length, purchases = run_single_game(rng=rng)
        game_lengths.append(game_length)
        total_purchases.update(purchases)

    average_game_length = sum(game_lengths) / len(game_lengths)

    return {
        "num_games": num_games,
        "average_game_length": average_game_length,
        "most_purchased_cards": total_purchases.most_common(top_n),
        "all_purchase_counts": dict(total_purchases),
    }
