from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import random
from pathlib import Path
from typing import Dict, List, Sequence

from src.engine import Card, Deck, Player


DEFAULT_WEIGHT_KEYS = ("damage", "armor", "heal", "draw", "finisher", "survival", "overkill")
LETHAL_CARD_SCORE = 1.0
GENERATION_SEED_STRIDE = 100
WEIGHT_PRECISION = 3
DEFAULT_WEIGHTS = {
    "damage": 1.2,
    "armor": 0.8,
    "heal": 1.0,
    "draw": 0.7,
    "finisher": 2.5,
    "survival": 1.4,
    "overkill": 0.05,
}

STANDARD_CARD_SPECS = (
    {"name": "Strike", "data": {"damage": 4}},
    {"name": "Heavy Blow", "data": {"damage": 6}},
    {"name": "Guard", "data": {"armor": 3}},
    {"name": "Barrier", "data": {"armor": 5}},
    {"name": "Recover", "data": {"heal": 3}},
    {"name": "Tactical Aid", "data": {"draw": 1}},
    {"name": "Balanced Stance", "data": {"damage": 2, "armor": 2}},
    {"name": "Second Wind", "data": {"heal": 2, "draw": 1}},
)


def _card_stat(card: Card, stat: str) -> int:
    value = card.data.get(stat, 0)
    return value if isinstance(value, int) else 0


def build_standard_deck(prefix: str = "card") -> Deck:
    cards = [
        Card(id=f"{prefix}-{idx}", name=spec["name"], data=dict(spec["data"]))
        for idx, spec in enumerate(STANDARD_CARD_SPECS)
    ]
    return Deck(cards)


class Strategy:
    name = "strategy"

    def choose_card(self, player: Player, opponent: Player, rng: random.Random) -> Card | None:
        raise NotImplementedError


class RandomStrategy(Strategy):
    name = "random"

    def choose_card(self, player: Player, opponent: Player, rng: random.Random) -> Card | None:
        if not player.hand:
            return None
        return rng.choice(player.hand)


class AggressiveStrategy(Strategy):
    name = "aggressive"

    def choose_card(self, player: Player, opponent: Player, rng: random.Random) -> Card | None:
        if not player.hand:
            return None
        return max(
            player.hand,
            key=lambda card: (_card_stat(card, "damage"), _card_stat(card, "draw"), _card_stat(card, "armor")),
        )


class DefensiveStrategy(Strategy):
    name = "defensive"

    def choose_card(self, player: Player, opponent: Player, rng: random.Random) -> Card | None:
        if not player.hand:
            return None
        if player.hp <= 10:
            return max(
                player.hand,
                key=lambda card: (_card_stat(card, "heal"), _card_stat(card, "armor"), _card_stat(card, "damage")),
            )
        return max(
            player.hand,
            key=lambda card: (_card_stat(card, "armor"), _card_stat(card, "heal"), _card_stat(card, "damage")),
        )


class WeightedStrategy(Strategy):
    name = "weighted"

    def __init__(self, weights: Dict[str, float] | None = None, name: str | None = None):
        merged = dict(DEFAULT_WEIGHTS)
        if weights:
            merged.update(weights)
        self.weights = merged
        if name:
            self.name = name

    def score_card(self, card: Card, player: Player, opponent: Player) -> float:
        damage = _card_stat(card, "damage")
        armor = _card_stat(card, "armor")
        heal = _card_stat(card, "heal")
        draw = _card_stat(card, "draw")
        opponent_armor = getattr(opponent, "armor", 0)
        opponent_total_health_pool = opponent.hp + opponent_armor
        overkill_damage = max(0, damage - opponent_total_health_pool)
        lethal_bonus = LETHAL_CARD_SCORE if damage == opponent_total_health_pool else 0.0
        survival_value = armor + heal if player.hp <= 10 else 0
        return (
            self.weights["damage"] * damage
            + self.weights["armor"] * armor
            + self.weights["heal"] * heal
            + self.weights["draw"] * draw
            + self.weights["finisher"] * lethal_bonus
            + self.weights["survival"] * survival_value
            + self.weights["overkill"] * overkill_damage
        )

    def choose_card(self, player: Player, opponent: Player, rng: random.Random) -> Card | None:
        if not player.hand:
            return None
        return max(player.hand, key=lambda card: (self.score_card(card, player, opponent), card.name))


@dataclass(frozen=True)
class MatchConfig:
    starting_hp: int = 20
    opening_hand: int = 3
    max_turns: int = 20


@dataclass(frozen=True)
class MatchResult:
    winner: str
    turns_played: int
    player_hp: int
    opponent_hp: int


@dataclass(frozen=True)
class StrategyEvaluation:
    average_score: float
    wins: int
    losses: int
    draws: int
    total_matches: int


@dataclass(frozen=True)
class TrainingSnapshot:
    generation: int
    average_score: float
    weights: Dict[str, float]


@dataclass(frozen=True)
class TrainingResult:
    strategy_name: str
    weights: Dict[str, float]
    evaluation: StrategyEvaluation
    history: List[TrainingSnapshot]

    def to_dict(self) -> Dict[str, object]:
        return {
            "strategy_name": self.strategy_name,
            "weights": dict(self.weights),
            "evaluation": asdict(self.evaluation),
            "history": [asdict(entry) for entry in self.history],
        }


class StrategyArena:
    def __init__(self, config: MatchConfig | None = None):
        self.config = config or MatchConfig()

    def _make_player(self, name: str, deck_prefix: str, rng: random.Random) -> Player:
        deck = build_standard_deck(deck_prefix)
        rng.shuffle(deck.cards)
        player = Player(name, deck=deck)
        player.hp = self.config.starting_hp
        player.max_hp = self.config.starting_hp
        player.armor = 0
        player.draw(self.config.opening_hand)
        return player

    def _apply_card(self, player: Player, opponent: Player, card: Card) -> None:
        damage = _card_stat(card, "damage")
        armor = _card_stat(card, "armor")
        heal = _card_stat(card, "heal")
        draw = _card_stat(card, "draw")

        if damage:
            blocked = min(getattr(opponent, "armor", 0), damage)
            opponent.armor = max(0, getattr(opponent, "armor", 0) - blocked)
            opponent.hp -= damage - blocked
        if armor:
            player.armor = getattr(player, "armor", 0) + armor
        if heal:
            player.hp = min(getattr(player, "max_hp", self.config.starting_hp), player.hp + heal)
        if draw:
            player.draw(draw)

    def play_match(self, player_strategy: Strategy, opponent_strategy: Strategy, seed: int) -> MatchResult:
        rng = random.Random(seed)
        player = self._make_player("player", "player", rng)
        opponent = self._make_player("opponent", "opponent", rng)
        active_player, active_strategy = player, player_strategy
        waiting_player, waiting_strategy = opponent, opponent_strategy

        final_turn = self.config.max_turns
        for turn in range(1, self.config.max_turns + 1):
            active_player.draw(1)
            card = active_strategy.choose_card(active_player, waiting_player, rng)
            if card is not None and card in active_player.hand:
                played = active_player.play_card(card)
                self._apply_card(active_player, waiting_player, played)

            if waiting_player.hp <= 0 or active_player.hp <= 0:
                final_turn = turn
                break

            active_player, waiting_player = waiting_player, active_player
            active_strategy, waiting_strategy = waiting_strategy, active_strategy

        if player.hp > opponent.hp:
            winner = "player"
        elif opponent.hp > player.hp:
            winner = "opponent"
        else:
            winner = "draw"

        return MatchResult(
            winner=winner,
            turns_played=final_turn,
            player_hp=player.hp,
            opponent_hp=opponent.hp,
        )


class StrategyTrainer:
    def __init__(
        self,
        arena: StrategyArena | None = None,
        baseline_strategies: Sequence[Strategy] | None = None,
        generations: int = 4,
        population_size: int = 6,
        matches_per_opponent: int = 4,
        mutation_scale: float = 0.8,
    ):
        self.arena = arena or StrategyArena()
        self.baseline_strategies = list(
            baseline_strategies or [RandomStrategy(), AggressiveStrategy(), DefensiveStrategy()]
        )
        self.generations = generations
        self.population_size = population_size
        self.matches_per_opponent = matches_per_opponent
        self.mutation_scale = mutation_scale

    def evaluate(self, strategy: Strategy, seed: int = 0) -> StrategyEvaluation:
        wins = losses = draws = 0
        total_score = 0.0
        match_seed = seed
        for opponent in self.baseline_strategies:
            for match_index in range(self.matches_per_opponent):
                if match_index % 2 == 0:
                    result = self.arena.play_match(strategy, opponent, match_seed)
                    player_is_candidate = True
                else:
                    result = self.arena.play_match(opponent, strategy, match_seed)
                    player_is_candidate = False
                match_seed += 1

                candidate_won = (result.winner == "player" and player_is_candidate) or (
                    result.winner == "opponent" and not player_is_candidate
                )
                candidate_lost = (result.winner == "opponent" and player_is_candidate) or (
                    result.winner == "player" and not player_is_candidate
                )

                if candidate_won:
                    wins += 1
                    total_score += 1.0
                elif candidate_lost:
                    losses += 1
                else:
                    draws += 1
                    total_score += 0.5

        total_matches = wins + losses + draws
        return StrategyEvaluation(
            average_score=(total_score / total_matches) if total_matches else 0.0,
            wins=wins,
            losses=losses,
            draws=draws,
            total_matches=total_matches,
        )

    def _mutate_weights(self, weights: Dict[str, float], rng: random.Random) -> Dict[str, float]:
        mutated = dict(weights)
        for key in DEFAULT_WEIGHT_KEYS:
            mutated[key] = round(
                max(0.0, mutated[key] + rng.uniform(-self.mutation_scale, self.mutation_scale)),
                WEIGHT_PRECISION,
            )
        return mutated

    def train(self, seed: int = 0) -> TrainingResult:
        rng = random.Random(seed)
        best_weights = dict(DEFAULT_WEIGHTS)
        best_evaluation = self.evaluate(WeightedStrategy(best_weights), seed=seed)
        history = [
            TrainingSnapshot(generation=0, average_score=best_evaluation.average_score, weights=dict(best_weights))
        ]

        for generation in range(1, self.generations + 1):
            candidates = [dict(best_weights)]
            while len(candidates) < self.population_size:
                candidates.append(self._mutate_weights(best_weights, rng))

            best_generation_weights = dict(best_weights)
            best_generation_evaluation = best_evaluation
            for candidate_index, candidate_weights in enumerate(candidates):
                evaluation = self.evaluate(
                    WeightedStrategy(candidate_weights),
                    seed=seed + (generation * GENERATION_SEED_STRIDE) + candidate_index,
                )
                if evaluation.average_score > best_generation_evaluation.average_score:
                    best_generation_weights = dict(candidate_weights)
                    best_generation_evaluation = evaluation

            best_weights = best_generation_weights
            best_evaluation = best_generation_evaluation
            history.append(
                TrainingSnapshot(
                    generation=generation,
                    average_score=best_evaluation.average_score,
                    weights=dict(best_weights),
                )
            )

        return TrainingResult(
            strategy_name="trained_weighted_strategy",
            weights=best_weights,
            evaluation=best_evaluation,
            history=history,
        )


def save_training_result(result: TrainingResult, output_path: str) -> Path:
    path = Path(output_path)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path
