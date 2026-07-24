"""Train V19: BC + fine-tune in the extended action space (v3).

Same recipe as V16 - the only one that has produced a real gain - applied to
the action space that now includes sacrifice and discard targeting. V16's
weights cannot transfer: the action space is 40 wide rather than 30, so the
clone is rebuilt from scratch against the v3 greedy teacher.

The question this answers is narrow and worth isolating: does exposing the
two decisions the project owner rates highest move the ~48% plateau that
V16/V17/V18 all converged on? Everything else is held fixed.
"""
import os

import numpy as np
import torch
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from stable_baselines3.common.callbacks import BaseCallback

from hero_rl_env_v3 import N_ACTIONS, HeroRealmsChoiceEnv

FIRE_GEM_PENALTY = -0.01
BC_EPISODES = 3000
BC_EPOCHS = 12
FINETUNE_STEPS = 800_000
CHECKPOINT_DIR = "models_v19"
EVAL_SEED_BASE = 100000
EVAL_EPISODES = 200
os.makedirs(CHECKPOINT_DIR, exist_ok=True)


def greedy_action(table):
    return max(table, key=lambda k: table[k].get("priority", 0))


def evaluate(policy_fn, n=EVAL_EPISODES, base=EVAL_SEED_BASE):
    """Fixed seeds so every number in this file is comparable to BASELINE.md."""
    env = HeroRealmsChoiceEnv(opponent_profile="random", fire_gem_penalty=FIRE_GEM_PENALTY)
    wins = 0
    for ep in range(n):
        obs, _ = env.reset(seed=base + ep)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            obs, reward, done, truncated, _ = env.step(policy_fn(env, obs))
        if done and reward > 0:
            wins += 1
    return wins / n


def collect_greedy_dataset(n_episodes=BC_EPISODES):
    """Roll out greedy and record (observation, action, mask) at every state."""
    env = HeroRealmsChoiceEnv(opponent_profile="random", fire_gem_penalty=FIRE_GEM_PENALTY)
    obs_buf, act_buf, mask_buf = [], [], []
    for ep in range(n_episodes):
        obs, _ = env.reset(seed=ep)
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
    """Saves alongside every eval. V16 reported a 55.5% checkpoint it had
    already overwritten; a win rate with no model behind it is not a result."""

    def __init__(self, eval_freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.save_dir = save_dir
        self.best = 0.0

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            self.model.save(os.path.join(self.save_dir, f"v19_{self.n_calls}"))
            wr = evaluate(lambda e, o: self.model.predict(
                o, action_masks=e.action_masks(), deterministic=True)[0])
            flag = ""
            if wr > self.best:
                self.best = wr
                self.model.save(os.path.join(self.save_dir, "v19_best"))
                flag = "  <- best"
            print(f"  Step {self.n_calls}: {wr:.1%}{flag}", flush=True)
        return True


env = HeroRealmsChoiceEnv(opponent_profile="random", fire_gem_penalty=FIRE_GEM_PENALTY)
model = MaskablePPO(
    MaskableActorCriticPolicy,
    env,
    verbose=0,
    learning_rate=1e-4,  # lower than V15's 3e-4: fine-tuning a clone, not exploring
    n_steps=2048,
    batch_size=256,
    n_epochs=5,
    gamma=0.99,
    gae_lambda=0.95,
    clip_range=0.2,
    ent_coef=0.005,  # V15's 0.01 kept it stochastic; less noise on top of a clone
    policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
)

print(f"Phase 1: cloning greedy from {BC_EPISODES} episodes...", flush=True)
obs_np, act_np, mask_np = collect_greedy_dataset()
print(f"  {len(obs_np)} state-action pairs", flush=True)

device = model.device
obs_t = torch.as_tensor(obs_np, device=device)
act_t = torch.as_tensor(act_np, device=device)
mask_t = torch.as_tensor(mask_np, device=device)

optimizer = torch.optim.Adam(model.policy.parameters(), lr=3e-4)
n = len(obs_t)
batch = 512
for epoch in range(BC_EPOCHS):
    perm = torch.randperm(n, device=device)
    total = 0.0
    for i in range(0, n, batch):
        idx = perm[i:i + batch]
        dist = model.policy.get_distribution(obs_t[idx], action_masks=mask_t[idx])
        loss = -dist.log_prob(act_t[idx]).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        total += loss.item() * len(idx)
    print(f"  epoch {epoch + 1}/{BC_EPOCHS} loss {total / n:.4f}", flush=True)

model.save(os.path.join(CHECKPOINT_DIR, "v19_bc"))
bc_wr = evaluate(lambda e, o: model.predict(o, action_masks=e.action_masks(), deterministic=True)[0])
print(f"\nBC clone: {bc_wr:.1%}  (greedy 37.5%, V15 best 36.5%)\n", flush=True)

print(f"Phase 2: PPO fine-tune for {FINETUNE_STEPS} steps...", flush=True)
model.learn(total_timesteps=FINETUNE_STEPS, callback=[EvalCallback(50000, CHECKPOINT_DIR)],
            reset_num_timesteps=False)

model.save(os.path.join(CHECKPOINT_DIR, "v19_final"))
final_wr = evaluate(lambda e, o: model.predict(o, action_masks=e.action_masks(), deterministic=True)[0])
print(f"\nBC {bc_wr:.1%} -> fine-tuned {final_wr:.1%}  (greedy 37.5%)", flush=True)
env.close()
