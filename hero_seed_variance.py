"""How much of a result is the shuffle and the seat, rather than the play?

Two questions, measured separately, because they are different worries:

  SEAT      Hero Realms is asymmetric by design - the first player draws 3, the
            second draws 5. A mirror match (identical policy both seats, same
            seeds) isolates that advantage from any question of skill.
  SHUFFLE   Play policies of widely differing strength through the *same* seeds
            and partition: seeds every policy wins, seeds no policy wins, and
            seeds where play decides. Only the contested band is addressable,
            so `1 - always_lost` bounds what any policy can reach.

Both must be re-measured after the Ruby fix and the Main-phase fix, each of
which changed the game. The existing hero_variance_ceiling.py answers the
second question on the RL env; this one answers both on hero_mcts_bench's
harness, which is where every recent number in BASELINE.md comes from.

Read the contested band as the real denominator. A 5pp difference between two
policies is 5pp of the *whole* sample but a much larger share of the games
either of them could actually have influenced - and conversely, if the
always-lost band is large, headline win rates are mostly reporting the deal.

Usage:
    python hero_seed_variance.py --seeds 150
"""
from __future__ import annotations

import argparse
import random

from hero_mcts_bench import MAX_ACTIONS_PER_GAME, _profile_action, play_game
from web.bot import apply_action, choose_bot_action
from web.opponent_profiles import PROFILE_WEIGHTS
from web.session import create_session


def mirror_first_player_rate(seeds, profile="balanced"):
    """Identical policy in both seats. Any deviation from 50% is the seat."""
    first_wins = 0
    played = 0
    for seed in seeds:
        random.seed(seed)
        session = create_session(seed=seed)
        steps = 0
        while session.winner is None and steps < MAX_ACTIONS_PER_GAME:
            apply_action(session, _profile_action(session, profile))
            steps += 1
        if session.winner == "draw" or session.winner is None:
            continue
        # `player` is the first seat (draws 3); `bot` is second (draws 5).
        first_wins += session.winner == "player"
        played += 1
    return first_wins / max(played, 1), played


def random_policy_game(profile, seed):
    random.seed(seed)
    session = create_session(seed=seed)
    steps = 0
    while session.winner is None and steps < MAX_ACTIONS_PER_GAME:
        if session.active_player == "player":
            apply_action(session, _profile_action(session, profile))
        else:
            actions = session.legal_actions()
            if not actions:
                break
            apply_action(session, random.choice(actions))
        steps += 1
    return session.winner


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=150)
    ap.add_argument("--base", type=int, default=1000)
    ap.add_argument("--profile", default="balanced")
    ap.add_argument("--strong-budget", type=int, default=240)
    args = ap.parse_args()

    seeds = list(range(args.base, args.base + args.seeds))

    rate, played = mirror_first_player_rate(seeds, args.profile)
    print(f"SEAT  mirror match ({args.profile} vs itself), {played} decisive games")
    print(f"      first player (draws 3) wins {rate:.1%}")
    print(f"      -> seat advantage is {abs(rate - 0.5) * 2:.1%} to the "
          f"{'first' if rate > 0.5 else 'second'} player\n")

    # Same seeds for every policy - that is the entire point of the partition.
    policies = {
        "random": lambda s: random_policy_game(args.profile, s),
        "heuristic": lambda s: play_game(args.profile, "heuristic", 60, s)[0],
        "mcts 60ms": lambda s: play_game(args.profile, "mcts", 60, s)[0],
        f"mcts {args.strong_budget}ms":
            lambda s: play_game(args.profile, "mcts", args.strong_budget, s)[0],
    }
    results = {}
    for name, run in policies.items():
        wins = [run(seed) == "bot" for seed in seeds]
        results[name] = wins
        print(f"      {name:<14} {sum(wins) / len(wins):.1%}", flush=True)

    always_won = sum(all(results[n][i] for n in results) for i in range(len(seeds)))
    always_lost = sum(not any(results[n][i] for n in results) for i in range(len(seeds)))
    contested = len(seeds) - always_won - always_lost

    print(f"\nSHUFFLE  {len(seeds)} seeds, every policy on the same ones")
    print(f"      always won  (even random)     {always_won:>4}  {always_won/len(seeds):.1%}")
    print(f"      always lost (even strongest)  {always_lost:>4}  {always_lost/len(seeds):.1%}")
    print(f"      contested   (play decides)    {contested:>4}  {contested/len(seeds):.1%}")
    print(f"\n      ceiling  ~= {1 - always_lost/len(seeds):.1%}   "
          f"(always-won + contested)")
    print(f"      floor    ~= {always_won/len(seeds):.1%}   "
          f"(what you get for showing up)")
    if contested:
        spread = ((sum(results[f'mcts {args.strong_budget}ms']) - sum(results['random']))
                  / contested)
        print(f"\n      strongest-minus-random across the contested band: {spread:+.1%}")
        print(f"      i.e. of the {contested} games play could influence, that is the "
              f"share it actually converts.")


if __name__ == "__main__":
    main()
