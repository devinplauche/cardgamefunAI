"""Public-information opponent buy models shared by benchmarks and MCTS.

The profiles intentionally mirror ``hero_mcts_bench``.  They may only consume
the visible market choices and the chosen market index recorded by a live
session; never use an opponent's private hand, deck, discard, or banish.
"""

from __future__ import annotations

import math
from typing import Any

from hero_ai import _buy_val
from hero_engine import FIRE_GEM


PROFILE_WEIGHTS = {
    "balanced": dict(gold_weight=2, combat_weight=2, health_weight=1, draw_weight=3),
    "aggressive": dict(combat_weight=2, draw_weight=3, champ_weight=3),
    "economic": dict(gold_weight=4, combat_weight=1, draw_weight=3, health_weight=1, champ_weight=2),
    "champion": dict(combat_weight=2, champ_weight=6),
}
PROFILE_NAMES = tuple(PROFILE_WEIGHTS)
_EPSILON = 0.12


def profile_buy_action(session, actions: list[dict[str, Any]], profile: str) -> dict[str, Any]:
    """Choose a buy exactly as the named benchmark profile would."""
    if profile not in PROFILE_WEIGHTS:
        raise ValueError(f"Unknown opponent profile: {profile}")
    weights = dict(PROFILE_WEIGHTS[profile])
    best, best_value = None, -1.0
    for action in actions:
        if action.get("type") != "buy_card":
            continue
        index = int(action["marketIndex"])
        if index == 5:  # Fire Gem is only a fallback in the benchmark profiles.
            continue
        card = session.market.row_cards()[index]
        if card is None:
            continue
        card_weights = dict(weights)
        if profile == "balanced":
            card_weights["champ_weight"] = card.health // 2
        value = float(_buy_val(card, **card_weights))
        if profile == "balanced":
            value -= card.cost // 2
        if value > best_value:
            best, best_value = action, value
    if best is not None:
        return best
    return next(
        (action for action in actions
         if action.get("type") == "buy_card" and int(action["marketIndex"]) == 5),
        {"type": "advance_phase"},
    )


def _profile_index_for_observation(profile: str, observation: Any,
                                   cards_by_id: dict[str, Any]) -> int | None:
    """Apply one profile to an immutable, public buy observation."""
    weights = dict(PROFILE_WEIGHTS[profile])
    best_index, best_value = None, -1.0
    for index, card_id in observation.buy_options:
        if index == 5:
            continue
        card = cards_by_id.get(card_id)
        if card is None:
            continue
        card_weights = dict(weights)
        if profile == "balanced":
            card_weights["champ_weight"] = card.health // 2
        value = float(_buy_val(card, **card_weights))
        if profile == "balanced":
            value -= card.cost // 2
        if value > best_value:
            best_index, best_value = index, value
    if best_index is not None:
        return best_index
    return next((index for index, _ in observation.buy_options if index == 5), None)


def inferred_profile_posterior(session, minimum_observations: int = 2) -> dict[str, float] | None:
    """Return a smoothed profile posterior from public opponent purchases.

    An observation contains the legal public options in the engine's priority
    order and the selected index. Ties are therefore replayed exactly without
    needing any private zones or historical state snapshots.
    """
    observations = session.opponent_purchase_observations
    if len(observations) < minimum_observations:
        return None
    cards_by_id = {card.id: card for card in session.cards}
    cards_by_id[FIRE_GEM.id] = FIRE_GEM
    log_weights = {profile: 0.0 for profile in PROFILE_NAMES}
    for observation in observations:
        choices = len(observation.buy_options)
        for profile in PROFILE_NAMES:
            predicted = _profile_index_for_observation(profile, observation, cards_by_id)
            if choices <= 1:
                likelihood = 1.0
            elif predicted == observation.chosen_market_index:
                likelihood = 1.0 - _EPSILON
            else:
                likelihood = _EPSILON / (choices - 1)
            log_weights[profile] += math.log(likelihood)
    maximum = max(log_weights.values())
    weights = {profile: math.exp(value - maximum) for profile, value in log_weights.items()}
    total = sum(weights.values())
    return {profile: value / total for profile, value in weights.items()}


def inferred_profile(session, minimum_observations: int = 2) -> str | None:
    posterior = inferred_profile_posterior(session, minimum_observations)
    if posterior is None:
        return None
    return max(PROFILE_NAMES, key=lambda profile: posterior[profile])
