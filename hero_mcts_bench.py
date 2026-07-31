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

from web.bot import _heuristic_rollout_action, apply_action, choose_bot_action
from web.opponent_profiles import PROFILE_WEIGHTS, profile_buy_action
from web.session import create_session

MAX_ACTIONS_PER_GAME = 4000


def _profile_action(session, profile):
    """Greedy profile-driven action for the opponent (first) seat."""
    actions = session.legal_actions()
    if not actions:
        return {"type": "advance_phase"}

    phase = session.phase
    if phase == "buy":
        return profile_buy_action(session, actions, profile)

    if phase == "combat":
        # legal_actions() now also offers non-guard champions as targets once
        # no guard remains, so "champion" actions here are not necessarily
        # guards despite the variable name below. Take lethal first if it is
        # on the table, or this would snipe a weak champion over ending the
        # game.
        buyer = session.player if session.active_player == "player" else session.bot
        opponent = session.bot if session.active_player == "player" else session.player
        if buyer.combat >= opponent.hp:
            lethal = next((a for a in actions if a["type"] == "attack_target"
                          and a.get("target") == "player"), None)
            if lethal is not None:
                return lethal

        face = next((a for a in actions if a["type"] == "attack_target"
                     and a.get("target") == "player"), None)
        champion_actions = [a for a in actions if a["type"] == "attack_target"
                            and a.get("target") == "champion"]
        board = {
            str(champion.instance_id): champion
            for champion in session.player.board + session.bot.board if champion.alive
        }
        # A missing face action means guards are still blocking. Damage that
        # cannot finish one will expire, but choosing the weakest guard retains
        # the profile's established attack-weakest policy.
        if face is None and champion_actions:
            return min(champion_actions, key=lambda action: (
                board.get(action.get("championId")).current_health
                if action.get("championId") in board else float("inf")
            ))
        killable = [
            action for action in champion_actions
            if action.get("championId") in board
            and board[action["championId"]].current_health <= buyer.combat
        ]
        if killable:
            return min(killable, key=lambda action: board[action["championId"]].current_health)
        if face is not None:
            return face
        if champion_actions:
            return champion_actions[0]
        return {"type": "advance_phase"}

    # play / champion phases: play everything, expend everything
    return _heuristic_rollout_action(session)


def play_game(profile, algorithm, budget_ms, seed, max_iterations=None,
              budget_scope="action"):
    """Play one benchmark game.

    ``budget_scope="action"`` preserves the original harness: every bot
    decision gets ``budget_ms``.  ``"turn"`` instead goes through
    ``GameSession.run_bot_turn()``, matching the web application's production
    action-allocation path.  The distinction matters for long rollouts: a
    buy followed by combat used to receive two independent 60 ms searches in
    this harness, while production currently grants a half-budget (minimum
    20 ms) slice to *each* searched choice.  It is therefore the right path
    comparison, not a strict wall-clock turn cap.
    """
    if budget_scope not in {"action", "turn"}:
        raise ValueError(f"Unknown budget scope: {budget_scope}")
    if budget_scope == "turn" and max_iterations is not None:
        raise ValueError("fixed iterations are only supported with action budget scope")
    random.seed(seed)
    session = create_session(seed=seed, algorithm=algorithm, budget_ms=budget_ms)
    steps = 0
    while session.winner is None and steps < MAX_ACTIONS_PER_GAME:
        if session.active_player == "player":
            apply_action(session, _profile_action(session, profile))
        else:
            if budget_scope == "turn":
                # Use the identical entry point as web/backend.py.  Count the
                # actions it performs so the benchmark's safety cap remains an
                # action cap rather than silently becoming a turn cap.
                session.run_bot_turn()
                # GameSession returns a serialised state for the web API; the
                # execution report itself is retained on the session.
                insight = session.last_bot_insight or {}
                steps += max(1, len(insight.get("actions", [])))
                continue
            action = choose_bot_action(session, budget_ms=budget_ms, algorithm=algorithm,
                                       max_iterations=max_iterations)
            apply_action(session, action)
        steps += 1
    return session.winner, session.turn_number, steps >= MAX_ACTIONS_PER_GAME


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--algorithms", nargs="*", default=["mcts", "heuristic"])
    ap.add_argument("--eval", choices=["search", "shaped", "hybrid"], default="search",
                    help="search: rollouts price everything; shaped: static card weights")
    ap.add_argument("--rollout-turns", type=int, default=None,
                    help="seat-turns simulated per rollout (default: web.bot.ROLLOUT_TURNS)")
    ap.add_argument("--utility", choices=["bounded", "raw"], default="bounded",
                    help="UCB reward scale: bounded is the production default; raw is a legacy A/B control")
    ap.add_argument("--root-sampling", choices=["independent", "paired", "ismcts"], default="paired",
                    help="independent UCB, paired common-random-number root rounds, "
                         "or a persistent information-set tree")
    ap.add_argument("--ismcts-depth", type=int, default=None,
                    help="searched bot decisions below the root (ismcts only)")
    ap.add_argument("--ismcts-exploration", type=float, default=None,
                    help="UCB exploration constant on bounded utility (ismcts only)")
    ap.add_argument("--ismcts-opponent-nodes", action="store_true",
                    help="give the opponent real minimax tree nodes (ismcts only)")
    ap.add_argument("--buy-root-width", type=int, default=3,
                    help="MCTS buy candidates retained at root; 0 keeps every legal action")
    ap.add_argument("--override-margin", type=float, default=0.10,
                    help="bounded-utility edge required to override the heuristic; -1 disables")
    ap.add_argument("--override-gate", choices=["margin", "confidence"], default="margin",
                    help="fixed mean margin or paired-delta confidence lower bound")
    ap.add_argument("--confidence-z", type=float, default=1.0,
                    help="one-sided standard-error multiplier for confidence gate")
    ap.add_argument("--confidence-min-worlds", type=int, default=4)
    ap.add_argument("--confidence-min-effect", type=float, default=0.0)
    ap.add_argument("--game-phase-weight", type=float, default=0.0,
                    help="tilt gold->combat as the game progresses; 0 is the control")
    ap.add_argument("--iterations", type=int, default=None,
                    help="root-simulation cap per decision (reproducible; paired rounds use complete batches)")
    ap.add_argument("--budget-scope", choices=["action", "turn"], default="action",
                    help="action: budget each bot choice (historical harness); "
                         "turn: use the production run_bot_turn path")
    ap.add_argument("--profiles", nargs="*", default=list(PROFILE_WEIGHTS),
                    choices=list(PROFILE_WEIGHTS))
    ap.add_argument("--buy-policy", choices=["situational", "static", "adaptive"], default="static",
                    help="live heuristic/root fallback buy policy")
    ap.add_argument("--rollout-buy-policy", choices=["situational", "static", "adaptive", "routed"],
                    default="adaptive",
                    help="situational: gold/combat priced against opponent HP and gold density; "
                         "static: original fixed-weight priority order; "
                         "adaptive: tilt toward combat when an opposing draw engine is visible; "
                         "routed: situational after public profile inference, adaptive otherwise")
    ap.add_argument("--opponent-rollout-policy", choices=["adaptive", "inferred", "posterior", "mixture"],
                    default="posterior",
                    help="adaptive: historical shared rollout; posterior: public-purchase Bayesian mixture")
    ap.add_argument("--opponent-model-min-observations", type=int, default=2,
                    help="public opponent buys required before profile rollout activates")
    args = ap.parse_args()

    if args.budget_scope == "turn" and args.iterations is not None:
        ap.error("--iterations is only supported with --budget-scope action")

    import web.bot as bot_module
    bot_module.EVAL_MODE = args.eval
    bot_module.BUY_POLICY = args.buy_policy
    bot_module.ROLLOUT_BUY_POLICY = args.rollout_buy_policy
    bot_module.OPPONENT_ROLLOUT_POLICY = args.opponent_rollout_policy
    bot_module.OPPONENT_MODEL_MIN_OBSERVATIONS = args.opponent_model_min_observations
    bot_module.MCTS_UTILITY_MODE = args.utility
    bot_module.ROOT_SAMPLING_MODE = args.root_sampling
    bot_module.ISMCTS_OPPONENT_NODES = args.ismcts_opponent_nodes
    if args.ismcts_depth is not None:
        bot_module.ISMCTS_MAX_DEPTH = args.ismcts_depth
    if args.ismcts_exploration is not None:
        bot_module.ISMCTS_EXPLORATION = args.ismcts_exploration
    bot_module.MCTS_BUY_ROOT_WIDTH = args.buy_root_width
    bot_module.GAME_PHASE_WEIGHT = args.game_phase_weight
    bot_module.MCTS_OVERRIDE_MARGIN = args.override_margin
    bot_module.MCTS_OVERRIDE_GATE = args.override_gate
    bot_module.MCTS_CONFIDENCE_Z = args.confidence_z
    bot_module.MCTS_CONFIDENCE_MIN_WORLDS = args.confidence_min_worlds
    bot_module.MCTS_CONFIDENCE_MIN_EFFECT = args.confidence_min_effect
    if args.rollout_turns is not None:
        bot_module.ROLLOUT_TURNS = args.rollout_turns
    print(f"eval={args.eval} rollout_turns={bot_module.ROLLOUT_TURNS} "
          f"buy_policy={args.buy_policy} rollout_buy_policy={args.rollout_buy_policy} "
          f"opponent_rollout_policy={args.opponent_rollout_policy} "
          f"opponent_model_min_observations={args.opponent_model_min_observations} "
          f"utility={args.utility} "
          f"root_sampling={args.root_sampling} buy_root_width={args.buy_root_width} "
          f"ismcts_depth={bot_module.ISMCTS_MAX_DEPTH} "
          f"ismcts_exploration={bot_module.ISMCTS_EXPLORATION} "
          f"ismcts_opponent_nodes={bot_module.ISMCTS_OPPONENT_NODES} "
          f"game_phase_weight={bot_module.GAME_PHASE_WEIGHT} "
          f"override_gate={args.override_gate} override_margin={args.override_margin} "
          f"confidence_z={args.confidence_z} confidence_min_worlds={args.confidence_min_worlds} "
          f"confidence_min_effect={args.confidence_min_effect}")

    search_limit = f"{args.iterations} simulation cap" if args.iterations is not None else f"{args.budget}ms"
    print(f"{args.games} seeded games per profile, MCTS {search_limit} per {args.budget_scope}")
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
                winner, _, stalled = play_game(profile, algorithm, args.budget, args.seed + i,
                                                max_iterations=args.iterations,
                                                budget_scope=args.budget_scope)
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
