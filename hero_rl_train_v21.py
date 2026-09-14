"""Parameterized BC + fine-tune trainer, so arms differ by a flag, not a file.

V15-V20 were each their own script with constants edited in place, which makes
an arm-to-arm comparison a diff review rather than a command line. Every knob
that distinguishes an arm here is an argument, and the recipe is otherwise V16's
unchanged - V16 is still the strongest RL model in the repo and the only one
that ever cleared greedy, so it is the recipe worth holding fixed.

The one methodological change: --seed trains an independent run. BASELINE.md's
V17 section is a worked example of checkpoint-selection bias in this project
(51.0% selected on the eval seeds, 49.0% re-measured on them, 47.2% held out),
and every run from V15 on is a single sample reported as a point estimate. At
~5k env steps/sec a run costs minutes, so there is no excuse for n=1.

Usage:
    python hero_rl_train_v21.py --env v4 --tag v21_obs --seed 0
    python hero_rl_train_v21.py --env v4 --shaping 0.5 --tag v21_pbrs --seed 0
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time

import numpy as np
import torch
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from stable_baselines3.common.callbacks import BaseCallback

FIRE_GEM_PENALTY = -0.01
EVAL_SEED_BASE = 100_000
EVAL_EPISODES = 200

# The nets here are two 256-wide layers on 256-row minibatches; intra-op
# parallelism buys almost nothing at that size and costs thread contention. One
# thread per process makes a run ~20% slower on its own but lets the whole
# ablation ladder run concurrently on 12 cores, which is the throughput that
# actually matters when the question needs 9 runs rather than 1.
torch.set_num_threads(1)


def make_env_factory(version, shaping, profile="random"):
    """One place that knows how to build each env version.

    `profile` exists so a *specialist* can be trained against one fixed
    opponent. Every run from V15 to V21 trained on the "random" 4-profile
    mixture, so no measurement in this repo separates "this is as well as the
    game can be played" from "this is as well as one policy can play against
    four opponents at once". A specialist bounds the difference.
    """
    if version == "v2":
        from hero_rl_env_v2 import HeroRealmsMaskedEnv

        return lambda: HeroRealmsMaskedEnv(opponent_profile=profile,
                                           fire_gem_penalty=FIRE_GEM_PENALTY)
    if version == "v3":
        from hero_rl_env_v3 import HeroRealmsChoiceEnv

        return lambda: HeroRealmsChoiceEnv(opponent_profile=profile,
                                           fire_gem_penalty=FIRE_GEM_PENALTY)
    if version == "v4":
        from hero_rl_env_v4 import HeroRealmsRichObsEnv

        return lambda: HeroRealmsRichObsEnv(opponent_profile=profile,
                                            fire_gem_penalty=FIRE_GEM_PENALTY,
                                            shaping_weight=shaping)
    raise ValueError(f"unknown env version: {version}")


def greedy_action(table):
    return max(table, key=lambda k: table[k].get("priority", 0))


def evaluate(policy_fn, env, n=EVAL_EPISODES, base=EVAL_SEED_BASE):
    """Win rate on fixed seeds.

    Deliberately counts `s.winner`, not the sign of the last reward: with
    shaping enabled the terminal reward is win/loss *plus* the final shaping
    term, so a reward-sign test would silently mismeasure the shaped arms.
    """
    wins = 0
    for episode in range(n):
        obs, _ = env.reset(seed=base + episode)
        done = truncated = False
        while not (done or truncated):
            obs, _, done, truncated, _ = env.step(policy_fn(env, obs))
        if env.session.winner == env.agent_side:
            wins += 1
    return wins / n


def collect_greedy_dataset(env, n_episodes):
    """Greedy trajectories. Greedy ignores the observation, so the *actions* are
    identical across env versions at a given seed and only the recorded
    observation differs - which is exactly what makes the arms comparable."""
    obs_buf, act_buf, mask_buf = [], [], []
    for episode in range(n_episodes):
        obs, _ = env.reset(seed=episode)
        done = truncated = False
        while not (done or truncated):
            action = greedy_action(env._action_table())
            obs_buf.append(obs)
            act_buf.append(action)
            mask_buf.append(env.action_masks())
            obs, _, done, truncated, _ = env.step(action)
    return (np.array(obs_buf, dtype=np.float32),
            np.array(act_buf, dtype=np.int64),
            np.array(mask_buf, dtype=bool))


class EvalCallback(BaseCallback):
    def __init__(self, eval_freq, eval_env, history, verbose=0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.eval_env = eval_env
        self.history = history

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            rate = evaluate(lambda e, o: self.model.predict(
                o, action_masks=e.action_masks(), deterministic=True)[0],
                self.eval_env)
            self.history.append((self.n_calls, rate))
            print(f"  step {self.n_calls}: {rate:.1%}", flush=True)
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", choices=["v2", "v3", "v4"], default="v4")
    ap.add_argument("--shaping", type=float, default=0.0,
                    help="potential-based shaping weight (v4 only; 0 disables)")
    ap.add_argument("--seed", type=int, default=0, help="training seed")
    ap.add_argument("--bc-episodes", type=int, default=3000)
    ap.add_argument("--bc-epochs", type=int, default=12)
    ap.add_argument("--steps", type=int, default=500_000)
    ap.add_argument("--eval-freq", type=int, default=50_000)
    ap.add_argument("--opponent-profile", default="random",
                    choices=["random", "balanced", "aggressive", "economic", "champion"],
                    help="train against one fixed profile (a specialist) or the mixture")
    ap.add_argument("--tag", default="v21")
    ap.add_argument("--outdir", default="models_v21")
    args = ap.parse_args()

    if args.shaping and args.env != "v4":
        ap.error("--shaping requires --env v4")

    os.makedirs(args.outdir, exist_ok=True)
    run = f"{args.tag}_s{args.seed}"
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    factory = make_env_factory(args.env, args.shaping, args.opponent_profile)
    env, eval_env = factory(), factory()
    started = time.time()

    print(f"run={run} env={args.env} shaping={args.shaping} seed={args.seed} "
          f"opponent={args.opponent_profile} "
          f"obs_dim={env.observation_space.shape[0]} actions={env.action_space.n}",
          flush=True)

    model = MaskablePPO(
        MaskableActorCriticPolicy, env, verbose=0, seed=args.seed,
        learning_rate=1e-4, n_steps=2048, batch_size=256, n_epochs=5,
        gamma=0.99, gae_lambda=0.95, clip_range=0.2, ent_coef=0.005,
        policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
    )

    print(f"phase 1: cloning greedy from {args.bc_episodes} episodes...", flush=True)
    obs_np, act_np, mask_np = collect_greedy_dataset(env, args.bc_episodes)
    print(f"  {len(obs_np)} state-action pairs", flush=True)

    device = model.device
    obs_t = torch.as_tensor(obs_np, device=device)
    act_t = torch.as_tensor(act_np, device=device)
    mask_t = torch.as_tensor(mask_np, device=device)
    optimizer = torch.optim.Adam(model.policy.parameters(), lr=3e-4)
    total = len(obs_t)
    for epoch in range(args.bc_epochs):
        perm = torch.randperm(total, device=device)
        running = 0.0
        for start in range(0, total, 512):
            index = perm[start:start + 512]
            dist = model.policy.get_distribution(obs_t[index], action_masks=mask_t[index])
            loss = -dist.log_prob(act_t[index]).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            running += loss.item() * len(index)
        print(f"  epoch {epoch + 1}/{args.bc_epochs} loss {running / total:.4f}", flush=True)

    model.save(os.path.join(args.outdir, f"{run}_bc"))
    predict = lambda e, o: model.predict(o, action_masks=e.action_masks(), deterministic=True)[0]
    bc_rate = evaluate(predict, eval_env)
    print(f"\nBC clone: {bc_rate:.1%}\n", flush=True)

    print(f"phase 2: PPO fine-tune for {args.steps} steps...", flush=True)
    history = []
    model.learn(total_timesteps=args.steps, reset_num_timesteps=False,
                callback=[EvalCallback(args.eval_freq, eval_env, history)])
    model.save(os.path.join(args.outdir, f"{run}_final"))
    final_rate = evaluate(predict, eval_env)

    # The best in-training checkpoint is recorded but deliberately not saved as
    # "best": selecting on the eval seeds and then reporting that number is the
    # V17 failure. Held-out measurement is hero_rl_eval_masked.py's job.
    best_step, best_rate = max(history, key=lambda item: item[1]) if history else (0, 0.0)
    summary = {
        "run": run, "env": args.env, "shaping": args.shaping, "seed": args.seed,
        "opponent_profile": args.opponent_profile,
        "bc": bc_rate, "final": final_rate,
        "best_in_training": best_rate, "best_step": best_step,
        "history": history, "elapsed_s": round(time.time() - started, 1),
    }
    with open(os.path.join(args.outdir, f"{run}.json"), "w") as handle:
        json.dump(summary, handle, indent=2)

    print(f"\nBC {bc_rate:.1%} -> final {final_rate:.1%} "
          f"(best in training {best_rate:.1%} @ {best_step}) "
          f"in {summary['elapsed_s']:.0f}s", flush=True)
    env.close()
    eval_env.close()


if __name__ == "__main__":
    main()
