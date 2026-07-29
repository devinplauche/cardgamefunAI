"""Trace the first bot-policy divergence on paired benchmark games.

This is a diagnostic, not an acceptance benchmark.  For every profile/seed it
runs the heuristic and MCTS from identical initial states, records their first
different bot action, then finishes both games independently.  Summaries focus
on discordant outcomes, where the first divergence is most actionable.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import web.bot as bot_module
from hero_engine import FIRE_GEM
from hero_mcts_bench import MAX_ACTIONS_PER_GAME, _profile_action
from web.bot import apply_action, choose_bot_action
from web.opponent_profiles import PROFILE_NAMES
from web.session import create_session


@dataclass(frozen=True)
class Divergence:
    phase: str
    heuristic: str
    mcts: str
    selection: str
    advantage: float | None
    buy_delta: tuple[tuple[str, float], ...] = ()


def _action_card(session, action: dict[str, Any]):
    if action.get("type") != "buy_card":
        return None
    index = int(action["marketIndex"])
    if index == 5:
        return FIRE_GEM
    return session.market.row_cards()[index]


def _card_features(card) -> dict[str, float]:
    if card is None:
        return {}
    return {
        "cost": float(card.cost),
        "combat": float(card.get("combat", 0)),
        "gold": float(card.get("gold", 0)),
        "draw": float(card.get("draw", 0)),
        "health": float(card.get("health", 0)),
        "champion_health": float(card.health if card.card_type == "champion" else 0),
        "guard": float(bool(card.guard)),
        "discard": float(
            card.get("opponent_discard", 0)
            + card.get("ally_opponent_discard", 0)
        ),
        "sacrifice": float(
            bool(card.get("sacrifice_card", False))
            + card.get("sacrifice_combat", 0)
        ),
    }


def _describe(session, action: dict[str, Any]) -> str:
    action_type = action.get("type", "?")
    if action_type == "buy_card":
        card = _action_card(session, action)
        return f"buy:{card.name if card is not None else '?'}"
    if action_type == "attack_target":
        if action.get("target") == "player":
            return "attack:face"
        opponent = session.player if session.active_player == "bot" else session.bot
        champion = next(
            (item for item in opponent.board
             if str(item.instance_id) == str(action.get("championId"))),
            None,
        )
        return f"attack:{champion.card.name if champion is not None else 'champion'}"
    if action_type in {"play_card", "expend_champion"}:
        # Labels contain the public card/champion name and stun target.
        return f"{action_type}:{action.get('label', '?')}"
    return action_type


def _normal_action(session, action: dict[str, Any]) -> tuple:
    """Compare semantic actions without process-global champion instance ids."""
    return (
        action.get("type"),
        _describe(session, action),
        action.get("marketIndex"),
        action.get("stunTargetIndex"),
        action.get("target"),
    )


def _first_divergence(profile: str, seed: int, iterations: int):
    heuristic = create_session(seed=seed, algorithm="heuristic")
    mcts = create_session(seed=seed, algorithm="mcts")
    steps = 0
    divergence = None

    while (heuristic.winner is None and mcts.winner is None
           and steps < MAX_ACTIONS_PER_GAME):
        if (heuristic.active_player, heuristic.phase) != (mcts.active_player, mcts.phase):
            raise AssertionError("paired games diverged before a different bot action")
        if heuristic.active_player == "player":
            h_action = _profile_action(heuristic, profile)
            m_action = _profile_action(mcts, profile)
        else:
            h_action = choose_bot_action(
                heuristic, algorithm="heuristic", max_iterations=iterations,
            )
            m_action = choose_bot_action(
                mcts, algorithm="mcts", max_iterations=iterations,
            )
            if _normal_action(heuristic, h_action) != _normal_action(mcts, m_action):
                buy_delta = ()
                if heuristic.phase == "buy":
                    h_features = _card_features(_action_card(heuristic, h_action))
                    m_features = _card_features(_action_card(mcts, m_action))
                    buy_delta = tuple(
                        (key, m_features.get(key, 0.0) - h_features.get(key, 0.0))
                        for key in h_features.keys() | m_features.keys()
                    )
                divergence = Divergence(
                    phase=heuristic.phase,
                    heuristic=_describe(heuristic, h_action),
                    mcts=_describe(mcts, m_action),
                    selection=str(m_action.get("selection", "unknown")),
                    advantage=m_action.get("utilityAdvantage"),
                    buy_delta=buy_delta,
                )
                apply_action(heuristic, h_action)
                apply_action(mcts, m_action)
                break

        apply_action(heuristic, h_action)
        apply_action(mcts, m_action)
        steps += 1

    return heuristic, mcts, divergence, steps


def _finish(session, profile: str, algorithm: str, iterations: int, steps: int):
    while session.winner is None and steps < MAX_ACTIONS_PER_GAME:
        action = (
            _profile_action(session, profile)
            if session.active_player == "player"
            else choose_bot_action(
                session, algorithm=algorithm, max_iterations=iterations,
            )
        )
        apply_action(session, action)
        steps += 1
    return session.winner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1_200_000)
    parser.add_argument("--iterations", type=int, default=16)
    parser.add_argument("--profiles", nargs="*", default=list(PROFILE_NAMES),
                        choices=list(PROFILE_NAMES))
    args = parser.parse_args()

    outcomes = Counter()
    categories: dict[str, Counter] = defaultdict(Counter)
    transitions: dict[str, Counter] = defaultdict(Counter)
    traits: dict[str, Counter] = defaultdict(Counter)
    deltas: dict[str, Counter] = defaultdict(Counter)
    advantages: dict[str, list[float]] = defaultdict(list)

    for profile_index, profile in enumerate(args.profiles):
        profile_seed = args.seed + profile_index * args.games
        for seed in range(profile_seed, profile_seed + args.games):
            heuristic, mcts, divergence, steps = _first_divergence(
                profile, seed, args.iterations,
            )
            h_winner = _finish(
                heuristic, profile, "heuristic", args.iterations, steps,
            )
            m_winner = _finish(mcts, profile, "mcts", args.iterations, steps)
            h_win, m_win = h_winner == "bot", m_winner == "bot"
            outcome = (
                "mcts_only" if m_win and not h_win
                else "heuristic_only" if h_win and not m_win
                else "both_win" if h_win
                else "both_loss"
            )
            outcomes[(profile, outcome)] += 1
            if divergence is None:
                categories[outcome]["no_divergence"] += 1
                continue
            categories[outcome][divergence.phase] += 1
            transitions[outcome][
                f"{divergence.heuristic} -> {divergence.mcts}"
            ] += 1
            for key, value in divergence.buy_delta:
                deltas[outcome][key] += value
            if divergence.buy_delta:
                delta = dict(divergence.buy_delta)
                if delta.get("combat", 0.0) <= -2.0:
                    traits[outcome]["combat_down_2plus"] += 1
                if delta.get("gold", 0.0) <= -1.0:
                    traits[outcome]["gold_down"] += 1
                if delta.get("champion_health", 0.0) > 0.0:
                    traits[outcome]["champion_health_up"] += 1
                if delta.get("health", 0.0) > 0.0:
                    traits[outcome]["healing_up"] += 1
                if divergence.mcts == "buy:Fire Gem":
                    traits[outcome]["mcts_fire_gem"] += 1
                if divergence.heuristic == "buy:Bribe":
                    traits[outcome]["abandons_bribe"] += 1
            if divergence.advantage is not None:
                advantage = float(divergence.advantage)
                advantages[outcome].append(advantage)
                if advantage < 0.18:
                    traits[outcome]["advantage_below_0.18"] += 1

    print("OUTCOMES")
    for profile in args.profiles:
        print(profile, dict(
            (outcome, outcomes[(profile, outcome)])
            for outcome in ("heuristic_only", "mcts_only", "both_win", "both_loss")
        ))
    for outcome in ("heuristic_only", "mcts_only"):
        count = sum(categories[outcome].values())
        print(f"\n{outcome.upper()} first divergences: {count}")
        print("phases", categories[outcome].most_common())
        print("transitions", transitions[outcome].most_common(15))
        print("overlapping buy traits", traits[outcome].most_common())
        buy_count = categories[outcome]["buy"]
        if buy_count:
            print("mean MCTS-minus-heuristic buy features", {
                key: round(value / buy_count, 3)
                for key, value in sorted(deltas[outcome].items())
            })
        if advantages[outcome]:
            print("mean reported utility advantage",
                  round(sum(advantages[outcome]) / len(advantages[outcome]), 4))


if __name__ == "__main__":
    main()
