"""Fit _buy_priority's weights against a cached oracle - zero-noise objective.

WHY THIS IS NOT hero_cma_fit.py AGAIN. That run failed, and BASELINE.md is
specific about why: "250 evaluations for 17 parameters at ~4.5pp noise each is
far too faint a signal for CMA-ES to follow." It also diagnosed the deeper
problem - "greedy win rate against heuristic profiles appears too insensitive
to buy ordering to fit against at any affordable sample size." Both are
measurement failures, not method failures, and both are fixable:

  * **Zero-variance objective.** Sample buy positions once, score every
    affordable option with a heavy oracle once, and cache the result.
    Evaluating a weight vector afterwards is a dot product against cached
    utilities - no games played, no sampling noise, microseconds per
    evaluation instead of minutes. CMA-ES can follow a signal it can actually
    see.
  * **6 parameters, not 17.** Only the buy_* terms enter `_buy_priority`. The
    other 11 are `_card_score` terms driving discard/sacrifice targeting - real
    decisions, but ones this objective does not measure and cannot fit. The
    original run optimised all 17 against an objective mixing both, badly
    under-determined.

WHAT IT OPTIMISES, and why that specific thing. `_buy_priority` is the sort key
`legal_actions()` uses, and `_root_search_actions` narrows to the top
MCTS_BUY_ROOT_WIDTH before the tree runs. Measured: 48.5% of buy decisions have
more than 3 affordable options, and in every one of those at least one legal
card is excluded from search entirely. So the fitness is not "does the greedy
pick match the oracle's pick" - it is **how much value does the top-K narrowing
throw away**:

    regret = best oracle utility overall
           - best oracle utility among the top-K by _buy_priority

Zero when the narrowing keeps the genuinely best option, whatever order it puts
it in. That is exactly the property the narrowing needs and nothing more.

THE ORACLE RUNS WITH MCTS_BUY_ROOT_WIDTH=0. Non-negotiable: with the shipped
width of 3, the oracle would only ever score the three options the current
weights already selected, so an underrated card excluded from the root would
have no utility to compare against and the objective would be blind to the
exact failure it is meant to measure. (hero_card_audit.py has this limitation -
its mean |gap| of 0.26 is measured only over positions where narrowing did not
bind, and so understates.)

CAVEAT, stated up front. The oracle shares the search's own objective, so this
fits `_buy_priority` to agree with what MCTS values - not with ground truth
about Hero Realms. That is the right target for the narrowing use case
(the gate should not hide what search would want to explore) but it means a
good fit here is *not* evidence the weights are correct in any deeper sense.
Transfer to win rate is a separate question, and given BASELINE.md's record -
three "obviously better" buy-valuation changes that all measured negative, plus
a margin-fitness fit that converged in-loop and then failed to transfer at
z=0.67 - the prior on transfer is poor. Fit here, then A/B properly.

Usage:
    python hero_buy_fit.py collect --positions 400
    python hero_buy_fit.py fit
"""
from __future__ import annotations

import argparse
import random

import numpy as np

# Only these enter _buy_priority. Order is this file's own; it does not have to
# match hero_weights.PARAM_ORDER since we never pack a full 17-vector.
BUY_PARAMS = ("buy_cost", "buy_combat", "buy_gold", "buy_draw",
              "buy_ally", "buy_sacrifice")
DATA_PATH = "models_value/buy_fit_data.npz"


def card_features(card, or_choice_fix: bool) -> np.ndarray:
    """Per-card feature vector aligned to BUY_PARAMS, so priority is a dot
    product. Mirrors web.session._buy_priority exactly - including the
    or_choice handling behind FIX_OR_CHOICE_DOUBLE_COUNT, so a fit done with
    the fix on stays valid when it ships."""
    effects = card.effects
    or_choice = effects.get("or_choice", []) if or_choice_fix else []
    if or_choice:
        # Mutually exclusive at resolution; only the best branch is ever
        # realised. Weight-dependent, so it cannot be folded into a static
        # feature - resolved per-candidate in _priorities instead.
        combat = gold = draw = 0.0
        branches = {kind: effects.get(kind, 0) for kind in or_choice
                    if kind in ("combat", "gold", "draw")}
    else:
        combat = effects.get("combat", 0)
        gold = effects.get("gold", 0)
        draw = effects.get("draw", 0)
        branches = {}
    ally = (effects.get("ally_combat", 0) + effects.get("ally_gold", 0)
            + effects.get("ally_health", 0) + effects.get("ally_draw", 0))
    return (np.array([card.cost, combat, gold, draw, ally,
                     1.0 if effects.get("sacrifice_card") else 0.0], dtype=np.float64),
            branches)


def _priorities(features, branch_list, weights: np.ndarray) -> np.ndarray:
    """Priority for each option under `weights`, resolving or_choice branches
    against the candidate weights (the branch that wins depends on them)."""
    base = features @ weights
    for index, branches in enumerate(branch_list):
        if not branches:
            continue
        lookup = {"combat": weights[1], "gold": weights[2], "draw": weights[3]}
        base[index] += max((amount * lookup[kind] for kind, amount in branches.items()),
                          default=0.0)
    return base


def collect(positions_wanted, oracle_sims, seed_base, or_choice_fix):
    """Cache oracle utilities for every affordable option in sampled positions."""
    import web.bot as bot_module
    import web.session as session_module
    from web.bot import (_action_key, _heuristic_rollout_action, apply_action,
                         choose_bot_action)
    from web.opponent_profiles import PROFILE_WEIGHTS, profile_buy_action
    from web.session import create_session

    previous_width = bot_module.MCTS_BUY_ROOT_WIDTH
    previous_fix = session_module.FIX_OR_CHOICE_DOUBLE_COUNT
    # Width 0 = no narrowing, so every affordable option gets an oracle score.
    bot_module.MCTS_BUY_ROOT_WIDTH = 0
    session_module.FIX_OR_CHOICE_DOUBLE_COUNT = or_choice_fix
    session_module._BUY_PRIORITY_CACHE.clear()

    rows_features, rows_branches, rows_utilities, rows_index = [], [], [], []
    profiles = list(PROFILE_WEIGHTS)
    seed = seed_base
    collected = 0
    try:
        while collected < positions_wanted and seed < seed_base + 3000:
            random.seed(seed)
            profile = profiles[seed % len(profiles)]
            session = create_session(seed=seed, algorithm="mcts")
            steps = 0
            while session.winner is None and steps < 400 and collected < positions_wanted:
                if session.active_player == "player":
                    actions = session.legal_actions()
                    apply_action(session, profile_buy_action(session, actions, profile)
                                 if session.phase == "buy" else _heuristic_rollout_action(session))
                else:
                    if session.phase == "buy":
                        buys = [a for a in session.legal_actions() if a["type"] == "buy_card"]
                        if len(buys) >= 2:
                            row = _score_position(session, buys, oracle_sims,
                                                 or_choice_fix, choose_bot_action,
                                                 _action_key)
                            if row is not None:
                                features, branches, utilities = row
                                rows_features.append(features)
                                rows_branches.append(branches)
                                rows_utilities.append(utilities)
                                rows_index.append(len(utilities))
                                collected += 1
                    apply_action(session, _heuristic_rollout_action(session))
                steps += 1
            seed += 1
    finally:
        bot_module.MCTS_BUY_ROOT_WIDTH = previous_width
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = previous_fix
        session_module._BUY_PRIORITY_CACHE.clear()

    return rows_features, rows_branches, rows_utilities


def _score_position(session, buys, oracle_sims, or_choice_fix,
                    choose_bot_action, _action_key):
    from hero_engine import FIRE_GEM

    result = choose_bot_action(session.clone(), algorithm="mcts",
                              max_iterations=oracle_sims)
    utility = {_action_key(c): c["averageUtility"] for c in result["candidates"]
               if c.get("averageUtility") is not None}
    row = session.market.row_cards()
    features, branches, utilities = [], [], []
    for action in buys:
        key = _action_key(action)
        if key not in utility:
            continue
        index = int(action.get("marketIndex", -1))
        card = FIRE_GEM if index == 5 else (row[index] if 0 <= index < len(row) else None)
        if card is None:
            continue
        vector, branch = card_features(card, or_choice_fix)
        features.append(vector)
        branches.append(branch)
        utilities.append(utility[key])
    if len(utilities) < 2:
        return None
    return np.array(features), branches, np.array(utilities)


def evaluate(weights, features_list, branches_list, utilities_list, top_k):
    """Mean value lost by top-K narrowing. Zero variance - no games played."""
    total = 0.0
    for features, branches, utilities in zip(features_list, branches_list, utilities_list):
        priorities = _priorities(features, branches, weights)
        keep = np.argsort(-priorities)[:top_k] if top_k > 0 else np.arange(len(priorities))
        total += float(utilities.max() - utilities[keep].max())
    return total / max(len(utilities_list), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    collect_ap = sub.add_parser("collect")
    collect_ap.add_argument("--positions", type=int, default=400)
    collect_ap.add_argument("--oracle", type=int, default=480)
    collect_ap.add_argument("--seed-base", type=int, default=30000)
    collect_ap.add_argument("--or-choice-fix", action="store_true")
    collect_ap.add_argument("--out", default=DATA_PATH)

    fit_ap = sub.add_parser("fit")
    fit_ap.add_argument("--data", default=DATA_PATH)
    fit_ap.add_argument("--top-k", type=int, default=3,
                       help="narrowing width the fit optimises for (MCTS_BUY_ROOT_WIDTH)")
    fit_ap.add_argument("--generations", type=int, default=200)
    fit_ap.add_argument("--holdout-frac", type=float, default=0.3)

    args = ap.parse_args()

    if args.command == "collect":
        import os
        import time

        print(f"collecting {args.positions} buy positions, oracle at {args.oracle} sims, "
              f"MCTS_BUY_ROOT_WIDTH=0 (no narrowing)...")
        start = time.time()
        features, branches, utilities = collect(args.positions, args.oracle,
                                                args.seed_base, args.or_choice_fix)
        print(f"  {len(utilities)} positions in {time.time() - start:.0f}s")
        counts = [len(u) for u in utilities]
        print(f"  options per position: mean {np.mean(counts):.1f}, "
              f"{sum(1 for c in counts if c > 3)} of {len(counts)} have >3 "
              f"(where width-3 narrowing binds)")

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        # Ragged; store flat with offsets.
        flat_features = np.concatenate(features)
        flat_utilities = np.concatenate(utilities)
        offsets = np.cumsum([0] + counts)
        branch_keys, branch_vals, branch_owner = [], [], []
        for position_index, position_branches in enumerate(branches):
            for option_index, branch in enumerate(position_branches):
                for kind, amount in branch.items():
                    branch_keys.append(kind)
                    branch_vals.append(amount)
                    branch_owner.append(offsets[position_index] + option_index)
        np.savez(args.out, features=flat_features, utilities=flat_utilities,
                 offsets=offsets, branch_keys=np.array(branch_keys, dtype=object),
                 branch_vals=np.array(branch_vals, dtype=np.float64),
                 branch_owner=np.array(branch_owner, dtype=np.int64),
                 or_choice_fix=args.or_choice_fix)
        print(f"saved to {args.out}")

    elif args.command == "fit":
        import hero_weights as W

        with np.load(args.data, allow_pickle=True) as data:
            flat_features = data["features"]
            flat_utilities = data["utilities"]
            offsets = data["offsets"]
            branch_keys = data["branch_keys"]
            branch_vals = data["branch_vals"]
            branch_owner = data["branch_owner"]

        features_list, branches_list, utilities_list = [], [], []
        owner_map = {}
        for key, value, owner in zip(branch_keys, branch_vals, branch_owner):
            owner_map.setdefault(int(owner), {})[str(key)] = float(value)
        for i in range(len(offsets) - 1):
            lo, hi = int(offsets[i]), int(offsets[i + 1])
            features_list.append(flat_features[lo:hi])
            branches_list.append([owner_map.get(j, {}) for j in range(lo, hi)])
            utilities_list.append(flat_utilities[lo:hi])

        cut = int(len(utilities_list) * (1 - args.holdout_frac))
        train = (features_list[:cut], branches_list[:cut], utilities_list[:cut])
        held = (features_list[cut:], branches_list[cut:], utilities_list[cut:])
        print(f"{len(utilities_list)} positions: {cut} fit, {len(held[2])} held out\n")

        baseline = np.array([W.DEFAULTS[name] for name in BUY_PARAMS], dtype=np.float64)
        base_fit = evaluate(baseline, *train, args.top_k)
        base_held = evaluate(baseline, *held, args.top_k)
        print(f"shipped weights {dict(zip(BUY_PARAMS, baseline))}")
        print(f"  narrowing loses  fit {base_fit:.5f}   held-out {base_held:.5f} "
              f"(utility; x62.5 for HP)\n")

        try:
            import cma
        except ImportError:
            raise SystemExit("pip install cma")

        es = cma.CMAEvolutionStrategy(list(baseline), 1.0,
                                     {"seed": 1, "verbose": -9,
                                      "maxiter": args.generations})
        while not es.stop():
            candidates = es.ask()
            es.tell(candidates, [evaluate(np.array(c), *train, args.top_k)
                                for c in candidates])
        best = np.array(es.result.xbest)
        fit_score = evaluate(best, *train, args.top_k)
        held_score = evaluate(best, *held, args.top_k)

        print(f"fitted weights {dict(zip(BUY_PARAMS, np.round(best, 3)))}")
        print(f"  narrowing loses  fit {fit_score:.5f}   held-out {held_score:.5f}")
        print(f"\nheld-out improvement: {(base_held - held_score) * 62.5:+.3f} HP per "
              f"buy decision ({(base_held - held_score) / max(base_held, 1e-9):+.1%})")
        print("\nThis is agreement with the search's own valuation, not ground truth.")
        print("Transfer to win rate is a separate question - A/B it before believing it.")


if __name__ == "__main__":
    main()
