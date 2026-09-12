"""Train V15: MaskablePPO over the unified action space (hero_rl_env_v2).

v14 was the last buy-only run: 19.5% final against random profiles, plateauing
because play/expend/combat/targeting were never the policy's to choose. In the
unified env, a naive highest-priority greedy policy scores 34% and uniform
random legal play scores 0% - so the space is expressive enough to play well
and leaves real headroom to learn.

Beating greedy (34%) is the bar that matters here, not beating v14 (19.5%);
they are different environments and the numbers are not comparable.
"""
import os

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from stable_baselines3.common.callbacks import BaseCallback

from hero_rl_env_v2 import HeroRealmsMaskedEnv

FIRE_GEM_PENALTY = -0.01
TOTAL_TIMESTEPS = 2_000_000
CHECKPOINT_DIR = "models_v15"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)


class CheckpointCallback(BaseCallback):
    def __init__(self, save_freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.save_dir = save_dir

    def _on_step(self):
        if self.n_calls % self.save_freq == 0:
            self.model.save(os.path.join(self.save_dir, f"v15_{self.n_calls}"))
        return True


class EvalCallback(BaseCallback):
    def __init__(self, eval_freq, n_episodes=200, verbose=0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.n_episodes = n_episodes

    def _on_step(self):
        if self.n_calls % self.eval_freq != 0:
            return True
        env = HeroRealmsMaskedEnv(opponent_profile="random",
                                  fire_gem_penalty=FIRE_GEM_PENALTY)
        wins = 0
        for ep in range(self.n_episodes):
            obs, _ = env.reset(seed=100000 + ep)
            done = truncated = False
            reward = 0.0
            while not (done or truncated):
                masks = env.action_masks()
                action, _ = self.model.predict(obs, action_masks=masks, deterministic=True)
                obs, reward, done, truncated, _ = env.step(action)
            if done and reward > 0:
                wins += 1
        print(f"  Step {self.n_calls}: {wins / self.n_episodes:.1%} ({wins}/{self.n_episodes})")
        return True


env = HeroRealmsMaskedEnv(opponent_profile="random", fire_gem_penalty=FIRE_GEM_PENALTY)
model = MaskablePPO(
    MaskableActorCriticPolicy,
    env,
    verbose=0,
    learning_rate=3e-4,
    n_steps=2048,
    batch_size=256,
    n_epochs=5,
    gamma=0.99,
    gae_lambda=0.95,
    clip_range=0.2,
    ent_coef=0.01,
    policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
)

print(f"Training V15 (MaskablePPO, unified action space) for {TOTAL_TIMESTEPS} steps...")
print(f"  Fire Gem penalty: {FIRE_GEM_PENALTY}")
print("  Network: 256x256 | Baselines in this env: random 0%, greedy 34%")
print()

model.learn(
    total_timesteps=TOTAL_TIMESTEPS,
    callback=[CheckpointCallback(100000, CHECKPOINT_DIR), EvalCallback(100000, 200)],
    reset_num_timesteps=False,
)

model.save(os.path.join(CHECKPOINT_DIR, "v15_final"))
env.close()
print(f"\nDone. Final model saved to {CHECKPOINT_DIR}/v15_final.zip")
