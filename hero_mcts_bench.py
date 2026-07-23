"""Benchmark the MCTS bot (web/bot.py) against the heuristic AI profiles.

This is a different harness from hero_rl_eval.py and the numbers are NOT
directly comparable to it:

  hero_rl_eval.py  agent seat = FIRST player (draws 3), buy-only action space
  this file        bot seat   = SECOND player (draws 5), full action space

`evaluate_state` in web/bot.py scores from `session.bot`'s perspective, so the
MCTS bot only plays the second seat. To keep the comparison honest, the
`heuristic` row measures web/bot.py's own greedy fallback in that same seat
against the same opponents and seeds. The MCTS-minus-heuristic delta is the
signal; the absolute number carries the second-player advantage.

Usage:
    python hero_mcts_bench.py                      # mcts and heuristic
    python hero_mcts_bench.py --games 50 --budget 60
"""

from __future__ import annotations

import argparse
import random
import time

from hero_ai import _buy_val
from web.bot import _heuristic_rollout_action, apply_action, choose_bot_action
from web.session import create_session

# Buy weights mirroring hero_ai's four profiles, so the opposition here matches
# the opposition in hero_rl_eval.py as closely as the phase machine allows.
PROFILE_WEIGHTS = {
    "balanced": dict(gold_weight=2, combat_weight=2, health_weight=1, draw_weight=3),
    "aggressive": dict(combat_weight=2, draw_weight=3, champ_weight=3),
    "economic": dict(gold_weight=4, combat_weight=1, draw_weight=3, health_weight=1, champ_weight=2),
    "champion": dict(combat_weight=2, champ_weight=6),
}

MAX_ACTIONS_PER_GAME = 4000


def _profile_action(session, profile):
    """Greedy profile-driven action for the opponent (first) seat."""
    actions = session.legal_actions()
    if not actions:
        return {"type": "advance_phase"}

    phase = session.phase
    if phase == "buy":
        weights = dict(PROFILE_WEIGHTS[profile])
        best, best_val = None, -1.0
        for action in actions:
            if action["type"] != "buy_card":
                continue
            idx = int(action["marketIndex"])
            if idx == 5:  # Fire Gem: only as a fallback
                continue
            card = session.market.row_cards()[idx]
            if card is None:
                continue
            w = dict(weights)
            if profile == "balanced":
                w["champ_weight"] = card.health // 2
            val = float(_buy_val(card, **w))
            if profile == "balanced":
                val -= card.cost // 2
            if val > best_val:
                best_val, best = val, action
        if best is not None:
            return best
        for action in actions:
            if action["type"] == "buy_card" and int(action["marketIndex"]) == 5:
                return action
        return {"type": "advance_phase"}

    if phase == "combat":
        # attack_weakest: guards sorted by lowest remaining health first
        guards = [a for a in actions if a["type"] == "attack_target" and a.get("target") == "champion"]
        if guards:
            board = {c.card.id: c for c in session.player.board + session.bot.board}
            return min(guards, key=lambda a: board[a["championId"]].current_health
                       if a["championId"] in board else 99)
        for action in actions:
            if action["type"] == "attack_target":
                return action
        return {"type": "advance_phase"}

    # play / champion phases: play everything, expend everything
    return _heuristic_rollout_action(session)


def play_game(profile, algorithm, budget_ms, seed):
    random.seed(seed)
    session = create_session(seed=seed, algorithm=algorithm, budget_ms=budget_ms)
    steps = 0
    while session.winner is None and steps < MAX_ACTIONS_PER_GAME:
        if session.active_player == "player":
            apply_action(session, _profile_action(session, profile))
        else:
            action = choose_bot_action(session, budget_ms=budget_ms, algorithm=algorithm)
            apply_action(session, action)
        steps += 1
    return session.winner, session.turn_number, steps >= MAX_ACTIONS_PER_GAME


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--algorithms", nargs="*", default=["mcts", "heuristic"])
    ap.add_argument("--eval", choices=["search", "shaped"], default="search",
                    help="search: rollouts price everything; shaped: static card weights")
    ap.add_argument("--rollout-turns", type=int, default=None,
                    help="seat-turns simulated per rollout (default: web.bot.ROLLOUT_TURNS)")
    ap.add_argument("--profiles", nargs="*", default=list(PROFILE_WEIGHTS),
                    choices=list(PROFILE_WEIGHTS))
    ap.add_argument("--buy-policy", choices=["situational", "static"], default="situational",
                    help="situational: gold/combat priced against opponent HP and gold density; "
                         "static: original fixed-weight priority order")
    args = ap.parse_args()

    import web.bot as bot_module
    bot_module.EVAL_MODE = args.eval
    bot_module.BUY_POLICY = args.buy_policy
    if args.rollout_turns is not None:
        bot_module.ROLLOUT_TURNS = args.rollout_turns
    print(f"eval={args.eval} rollout_turns={bot_module.ROLLOUT_TURNS} buy_policy={args.buy_policy}")

    print(f"{args.games} seeded games per profile, MCTS budget {args.budget}ms")
    print("bot seat = second player (draws 5); see module docstring on comparability\n")
    header = f"{'algorithm':<14}" + "".join(f"{p:>12}" for p in args.profiles) + f"{'AVG':>9}{'s/game':>9}"
    print(header)
    print("-" * len(header))

    for algorithm in args.algorithms:
        rates, stalls = [], 0
        t0 = time.perf_counter()
        for profile in args.profiles:
            wins = 0
            for i in range(args.games):
                winner, _, stalled = play_game(profile, algorithm, args.budget, args.seed + i)
                wins += winner == "bot"
                stalls += stalled
            rates.append(wins / args.games)
            print(f"  [{algorithm}] {profile}: {wins}/{args.games}"
                  f"  ({time.perf_counter() - t0:.0f}s elapsed)", flush=True)
        elapsed = time.perf_counter() - t0
        per_game = elapsed / (args.games * len(args.profiles))
        line = f"{algorithm:<14}" + "".join(f"{r:>11.1%} " for r in rates)
        print(f"{line}{sum(rates)/len(rates):>8.1%}{per_game:>9.2f}")
        if stalls:
            print(f"  warning: {stalls} game(s) hit the {MAX_ACTIONS_PER_GAME}-action cap")


if __name__ == "__main__":
    main()
