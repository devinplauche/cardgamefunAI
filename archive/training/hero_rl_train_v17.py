"""Train V17: continue V16's fine-tune, with checkpointing this time.

V16 answered the question V15 posed. Behavior-cloning greedy and then fine-
tuning with PPO reached 47-55% against random profiles, versus greedy's 37.5%
and V15-from-random-init's 36.5% ceiling. The warm start was the missing
piece: PPO could improve on greedy, it just could not find greedy's region of
policy space on its own from a terminal-only reward.

V16 had no checkpoint callback in phase 2, only an eval callback, so its best
observed model (55.5% at 350k steps) was overwritten and is gone - only the
final 47% model survives. This run continues from that survivor and saves
every 50k so the best model is actually recoverable.

Still open, and not addressed here: the opponents are fixed heuristic profiles,
so this measures "beats these four bots", not general strength. Self-play is
the next structural step, not more steps against the same opposition.
"""
import os

from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import BaseCallback

from hero_rl_env_v2 import HeroRealmsMaskedEnv

FIRE_GEM_PENALTY = -0.01
TOTAL_TIMESTEPS = 1_500_000
CHECKPOINT_DIR = "models_v17"
EVAL_SEED_BASE = 100000
EVAL_EPISODES = 200
os.makedirs(CHECKPOINT_DIR, exist_ok=True)


def evaluate(model, n=EVAL_EPISODES, base=EVAL_SEED_BASE, profile="random"):
    env = HeroRealmsMaskedEnv(opponent_profile=profile, fire_gem_penalty=FIRE_GEM_PENALTY)
    wins = 0
    for ep in range(n):
        obs, _ = env.reset(seed=base + ep)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            action, _ = model.predict(obs, action_masks=env.action_masks(), deterministic=True)
            obs, reward, done, truncated, _ = env.step(action)
        if done and reward > 0:
            wins += 1
    return wins / n


class CheckpointEvalCallback(BaseCallback):
    """Save and evaluate together, so every reported win rate has a model file
    behind it - V16's best run is gone precisely because it did not."""

    def __init__(self, freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.freq = freq
        self.save_dir = save_dir
        self.best = 0.0

    def _on_step(self):
        if self.n_calls % self.freq != 0:
            return True
        path = os.path.join(self.save_dir, f"v17_{self.n_calls}")
        self.model.save(path)
        wr = evaluate(self.model)
        flag = ""
        if wr > self.best:
            self.best = wr
            self.model.save(os.path.join(self.save_dir, "v17_best"))
            flag = "  <- best"
        print(f"  Step {self.n_calls}: {wr:.1%}{flag}", flush=True)
        return True


env = HeroRealmsMaskedEnv(opponent_profile="random", fire_gem_penalty=FIRE_GEM_PENALTY)
model = MaskablePPO.load("models_v16/v16_final", env=env)
model.learning_rate = 1e-4
model.ent_coef = 0.005

print(f"V17: continuing V16 fine-tune for {TOTAL_TIMESTEPS} steps (checkpointed every 50k)")
print("  Reference points: greedy 37.5%, V15 best 36.5%, V16 final 47.0%")
print()

tracker = CheckpointEvalCallback(50000, CHECKPOINT_DIR)
model.learn(total_timesteps=TOTAL_TIMESTEPS, callback=[tracker], reset_num_timesteps=False)

model.save(os.path.join(CHECKPOINT_DIR, "v17_final"))
print(f"\nFinal: {evaluate(model):.1%}   Best seen: {tracker.best:.1%}")
print(f"Best checkpoint saved to {CHECKPOINT_DIR}/v17_best.zip")
env.close()
