"""A learned value function for MCTS leaves - the untried combination.

Every strong published deckbuilder result pairs MCTS with a value function
(Dominion's shipped AlphaZero-style AI, Temple Gates' card-embedding network);
this repo has built RL policies (V16-V21) and built search, and never joined
them. That is the gap this fills.

WHAT PROBLEM THIS ACTUALLY TARGETS. Not leaf accuracy: hero_horizon60_ab.py
already showed the rollout's terminal HP-diff is a *good* estimator of the
eventual outcome (replacing truncated rollouts with real playouts flipped 30%
of games and netted zero). The target is COST. `_rollout` costs ~1.6ms; the
network's forward pass alone is ~50us, but everything else in a search
iteration (clone, apply_action, node bookkeeping) costs the same regardless, so
the measured *whole-decision* speedup at 60ms is ~13x (33 iterations ->
438) - real, but well short of what the isolated numbers imply. Still the
mechanism that starved ISMCTS and ensemble determinization (each tree got as
few as ~13 iterations before the budget ran out); a cheap-enough leaf evaluator
could plausibly resurrect either.

TRAINING TARGET: distillation, not a new source of truth. The label for a
position is the mean of `_search_utility(_rollout(...))` over K independent
rollouts using the exact rollout policy the search already uses. So the network
is trained to predict what many rollouts from a leaf would average to - the
same validated evaluator, just fast - rather than asserting a new opinion about
the game. Risk this does NOT remove: whatever blind spots the rollout policy
itself has (see BASELINE.md's "rollout is not the place to add knowledge"
findings) are distilled in along with everything the rollout gets right.

FEATURES. A dozen or so scalars built from functions already used to value
positions elsewhere in this file (`_deck_quality`, `_board_value`,
`_deck_gold_density`, `_junk_count`), plus faction concentration - not the
645-dim hero_rl_env_v4 observation. Two reasons: this trains on thousands of
positions, not millions, so a lower-dimensional target is the right bias/variance
tradeoff; and v4's richness was validated (or rather, invalidated) for a
40-way policy classification, not a scalar regression, so reusing it here would
carry an unrelated negative result by association.

INFERENCE HAS NO TORCH DEPENDENCY. Training uses torch for convenience; the
exported model is plain NumPy arrays run through a hand-written forward pass, so
the live search process never imports torch or spins up its thread pool - the
same concern hero_rl_train_v21.py documents for training runs applies doubly to
a process serving live requests.

USAGE

    python hero_value_net.py train --positions 3000 --rollouts 20
    python hero_value_net.py eval --positions 200      # regret-style sanity check

Then in web/bot.py: LEAF_EVAL_MODE = "value_net" (default "rollout").
"""
from __future__ import annotations

import argparse
import random
import time

import numpy as np

from hero_engine import HRGame, _deck_gold_density
from hero_rl_env_v2 import FACTIONS
from web.opponent_profiles import PROFILE_WEIGHTS, profile_buy_action
from web.session import create_session

FEATURE_NAMES = (
    "hp_diff", "own_hp", "opp_hp", "gold", "combat", "turn",
    "deck_quality_diff", "own_deck_quality",
    "board_value_diff", "own_board_value",
    "own_champs", "opp_champs",
    "own_gold_density", "opp_gold_density", "own_junk", "hand_size",
    "own_guild", "own_imperial", "own_necros", "own_wild",
    "opp_guild", "opp_imperial", "opp_necros", "opp_wild",
)
FEATURE_DIM = len(FEATURE_NAMES)

DEFAULT_MODEL_PATH = "models_value/value_net_v1.npz"
HIDDEN_SIZES = (32, 16)


def _faction_counts(player) -> dict[str, int]:
    owned = (list(player.deck) + list(player.hand) + list(player.discard)
             + [bc.card for bc in player.board if bc.alive])
    counts = {f: 0 for f in FACTIONS}
    for card in owned:
        faction = (card.faction or "").lower()
        if faction in counts:
            counts[faction] += 1
    return counts


def extract_features(session) -> np.ndarray:
    """Feature vector for the bot seat, valid at any point in a game.

    `_rollout`'s entry state is whatever the search's descent landed on - the
    bot's own turn most of the time, but potentially mid-opponent-turn under
    ISMCTS/ensemble's `_advance_to_decision` - so this makes no phase or
    active-player assumption. Reads `player.deck` etc. directly; at real
    inference time the session is always an already-determinized clone (see
    determinize_for_bot), so this carries no more information than the rollout
    policy already legitimately uses to drive the opponent's turns.
    """
    from web.bot import _board_value, _deck_quality, _junk_count

    bot, opponent = session.bot, session.player
    own_fac = _faction_counts(bot)
    opp_fac = _faction_counts(opponent)
    own_board = [bc for bc in bot.board if bc.alive]
    opp_board = [bc for bc in opponent.board if bc.alive]

    return np.array([
        (bot.hp - opponent.hp) / HRGame.STARTING_HP,
        bot.hp / HRGame.STARTING_HP,
        opponent.hp / HRGame.STARTING_HP,
        min(bot.gold, 20) / 20.0,
        min(bot.combat, 20) / 20.0,
        min(session.turn_number, 40) / 40.0,
        np.tanh((_deck_quality(bot) - _deck_quality(opponent)) / 10.0),
        np.tanh(_deck_quality(bot) / 10.0),
        np.tanh((_board_value(bot.board) - _board_value(opponent.board)) / 10.0),
        np.tanh(_board_value(bot.board) / 10.0),
        len(own_board) / 6.0,
        len(opp_board) / 6.0,
        _deck_gold_density(bot),
        _deck_gold_density(opponent),
        _junk_count(bot) / 10.0,
        min(len(bot.hand), 10) / 10.0,
        *(own_fac[f] / 8.0 for f in FACTIONS),
        *(opp_fac[f] / 8.0 for f in FACTIONS),
    ], dtype=np.float32)


class TinyMLP:
    """Hand-written forward pass. No torch import, so the live search process
    never loads it."""

    def __init__(self, weights: dict[str, np.ndarray]):
        self.weights = weights

    def predict(self, features: np.ndarray) -> float:
        x = features
        for index in range(len(self.weights) // 2 - 1):
            x = np.tanh(x @ self.weights[f"w{index}"] + self.weights[f"b{index}"])
        last = len(self.weights) // 2 - 1
        logit = x @ self.weights[f"w{last}"] + self.weights[f"b{last}"]
        return float(1.0 / (1.0 + np.exp(-logit[0])))  # sigmoid -> (0, 1)

    @classmethod
    def load(cls, path: str) -> "TinyMLP":
        with np.load(path) as data:
            weights = {key: data[key] for key in data.files}
        return cls(weights)

    def save(self, path: str) -> None:
        np.savez(path, **self.weights)


# ---- data generation ----

def _sample_positions(count, seed_base, rng):
    """Snapshot states from self-play games under mixed profiles.

    Unfiltered on phase or active player, unlike hero_regret.py's buy/combat
    sampling: `_rollout` can be entered at any point the search's descent
    stopped, so training data should look the same way.
    """
    from web.bot import _heuristic_rollout_action, apply_action

    positions = []
    seed = seed_base
    profiles = list(PROFILE_WEIGHTS)
    while len(positions) < count:
        random.seed(seed)
        profile = profiles[seed % len(profiles)]
        session = create_session(seed=seed, algorithm="mcts")
        steps = 0
        while session.winner is None and steps < 300 and len(positions) < count:
            if session.active_player == "player":
                actions = session.legal_actions()
                action = (profile_buy_action(session, actions, profile)
                          if session.phase == "buy" else _heuristic_rollout_action(session))
            else:
                action = _heuristic_rollout_action(session)
            apply_action(session, action)
            steps += 1
            if rng.random() < 0.15:  # sparse snapshots so nearby states don't dominate
                positions.append(session.clone())
        seed += 1
    return positions[:count]


def generate_dataset(count, rollouts_per_position, seed_base=9000):
    """(features, label) pairs. label = mean bounded utility over K rollouts,
    i.e. what the search's own evaluator would average to from this leaf."""
    from web.bot import _rollout, _search_utility

    rng = random.Random(seed_base)
    positions = _sample_positions(count, seed_base, rng)
    features = np.zeros((len(positions), FEATURE_DIM), dtype=np.float32)
    labels = np.zeros(len(positions), dtype=np.float32)
    for index, position in enumerate(positions):
        features[index] = extract_features(position)
        utilities = [_search_utility(_rollout(position.clone()))
                     for _ in range(rollouts_per_position)]
        labels[index] = sum(utilities) / len(utilities)
    return features, labels


def train(features, labels, val_features=None, val_labels=None,
         hidden_sizes=HIDDEN_SIZES, epochs=300, seed=0, weight_decay=1e-3,
         patience=30):
    """Adam + L2 + early stopping on a validation split.

    Labels are bimodal (most rollouts at ROLLOUT_TURNS=16 end in an actual
    win/loss, per the horizon measurement), so a handful of noisy 8-rollout
    labels on ~200 positions overfit badly - held-out MAE came in *worse* than
    predicting a constant. Early stopping on a real validation set, plus L2, is
    what makes the position/rollout count in `train`'s CLI defaults trustworthy
    rather than just a bigger number.
    """
    import torch

    torch.manual_seed(seed)
    x = torch.as_tensor(features)
    y = torch.as_tensor(labels).unsqueeze(1)
    has_val = val_features is not None and len(val_features) > 0
    if has_val:
        vx = torch.as_tensor(val_features)
        vy = torch.as_tensor(val_labels).unsqueeze(1)

    sizes = (FEATURE_DIM,) + tuple(hidden_sizes) + (1,)
    layers = [torch.nn.Linear(sizes[i], sizes[i + 1]) for i in range(len(sizes) - 1)]
    model = torch.nn.ModuleList(layers)

    def forward(inputs):
        h = inputs
        for layer in layers[:-1]:
            h = torch.tanh(layer(h))
        return torch.sigmoid(layers[-1](h))

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=weight_decay)
    loss_fn = torch.nn.BCELoss()  # targets are already probabilities in (0,1)
    n = len(x)
    best_val, best_state, stale = float("inf"), None, 0
    for epoch in range(epochs):
        permutation = torch.randperm(n)
        total = 0.0
        for start in range(0, n, 128):
            index = permutation[start:start + 128]
            optimizer.zero_grad()
            loss = loss_fn(forward(x[index]), y[index])
            loss.backward()
            optimizer.step()
            total += loss.item() * len(index)

        with torch.no_grad():
            check_x, check_y = (vx, vy) if has_val else (x, y)
            val_mae = (forward(check_x) - check_y).abs().mean().item()
        if val_mae < best_val - 1e-5:
            best_val, stale = val_mae, 0
            best_state = [(layer.weight.clone(), layer.bias.clone()) for layer in layers]
        else:
            stale += 1
        if epoch % 50 == 0 or epoch == epochs - 1:
            print(f"  epoch {epoch:>4} loss {total / n:.4f}  "
                  f"{'val' if has_val else 'train'} MAE {val_mae:.4f}", flush=True)
        if stale >= patience:
            print(f"  early stop at epoch {epoch} (no improvement for {patience})", flush=True)
            break

    if best_state is not None:
        for layer, (weight, bias) in zip(layers, best_state):
            layer.weight.data.copy_(weight)
            layer.bias.data.copy_(bias)

    weights = {}
    for i, layer in enumerate(layers):
        weights[f"w{i}"] = layer.weight.detach().numpy().T.astype(np.float32)
        weights[f"b{i}"] = layer.bias.detach().numpy().astype(np.float32)
    return TinyMLP(weights)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    train_ap = sub.add_parser("train")
    train_ap.add_argument("--positions", type=int, default=3000)
    train_ap.add_argument("--rollouts", type=int, default=20,
                          help="rollouts averaged per label; lower = noisier target")
    train_ap.add_argument("--epochs", type=int, default=300)
    train_ap.add_argument("--out", default=DEFAULT_MODEL_PATH)
    train_ap.add_argument("--holdout-frac", type=float, default=0.15)

    eval_ap = sub.add_parser("eval",
                             description="Regret-style sanity check: does the "
                             "net's implied ranking agree with a heavy oracle?")
    eval_ap.add_argument("--model", default=DEFAULT_MODEL_PATH)
    eval_ap.add_argument("--positions", type=int, default=100)
    eval_ap.add_argument("--rollouts", type=int, default=40)

    args = ap.parse_args()

    if args.command == "train":
        import os
        print(f"generating {args.positions} positions, {args.rollouts} rollouts each...")
        start = time.time()
        features, labels = generate_dataset(args.positions, args.rollouts)
        print(f"  done in {time.time() - start:.0f}s. label mean {labels.mean():.3f} "
              f"sd {labels.std():.3f}")

        # Three-way split: val drives early stopping, test is never touched
        # until the final number, or "held-out" would really be "tuned-on".
        n = len(features)
        val_cut = int(n * (1 - 2 * args.holdout_frac))
        test_cut = int(n * (1 - args.holdout_frac))
        model = train(features[:val_cut], labels[:val_cut],
                     features[val_cut:test_cut], labels[val_cut:test_cut],
                     epochs=args.epochs)

        test_features, test_labels = features[test_cut:], labels[test_cut:]
        predictions = np.array([model.predict(f) for f in test_features])
        mae = np.mean(np.abs(predictions - test_labels))
        baseline_mae = np.mean(np.abs(test_labels.mean() - test_labels))
        print(f"\ntest MAE {mae:.4f} (predicting the test set's own mean would "
              f"score {baseline_mae:.4f} - the model must beat this)")
        if mae >= baseline_mae:
            print("WARNING: the model does not beat predicting a constant. "
                  "Not saving; generate more positions/rollouts and retrain.")
            return

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        model.save(args.out)
        print(f"saved to {args.out}")

    elif args.command == "eval":
        from web.bot import _rollout, _search_utility

        model = TinyMLP.load(args.model)
        rng = random.Random(1234)
        positions = _sample_positions(args.positions, 20000, rng)
        errors = []
        for position in positions:
            predicted = model.predict(extract_features(position))
            actual = sum(_search_utility(_rollout(position.clone()))
                        for _ in range(args.rollouts)) / args.rollouts
            errors.append(abs(predicted - actual))
        print(f"{len(errors)} fresh positions, mean |error| vs a "
              f"{args.rollouts}-rollout oracle: {np.mean(errors):.4f}")


if __name__ == "__main__":
    main()
