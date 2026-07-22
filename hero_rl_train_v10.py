"""Train V10: pure end-game reward, 2M timesteps, 128 hidden, random opponent."""
import os
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from hero_engine import load_hero_cards
from hero_rl_env import HeroRealmsEnv

cards = load_hero_cards("data/hero_realms_cards.json")

TOTAL_TIMESTEPS = 2_000_000
CHECKPOINT_DIR = "models_v10"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

class CheckpointCallback(BaseCallback):
    def __init__(self, save_freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.save_dir = save_dir

    def _on_step(self):
        if self.n_calls % self.save_freq == 0:
            path = os.path.join(self.save_dir, f"v10_{self.n_calls}")
            self.model.save(path)
        return True

class EvalCallback(BaseCallback):
    def __init__(self, eval_freq, n_episodes=200, verbose=0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.n_episodes = n_episodes

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            wins = 0
            for _ in range(self.n_episodes):
                env = HeroRealmsEnv(cards, opponent_profile="random")
                obs, _ = env.reset()
                done = False
                while not done:
                    action, _ = self.model.predict(obs, deterministic=True)
                    obs, _, done, truncated, _ = env.step(action)
                    if truncated:
                        break
                if env.winner == env.agent.name:
                    wins += 1
                env.close()
            wr = wins / self.n_episodes
            print(f"  Step {self.n_calls}: {wr:.1%} ({wins}/{self.n_episodes})")
        return True

env = HeroRealmsEnv(cards, opponent_profile="random")
model = PPO(
    "MlpPolicy",
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
    policy_kwargs=dict(net_arch=dict(pi=[128, 128], vf=[128, 128])),
)

callback = CheckpointCallback(save_freq=100000, save_dir=CHECKPOINT_DIR)
eval_cb = EvalCallback(eval_freq=100000, n_episodes=200)

print(f"Training V10 for {TOTAL_TIMESTEPS} timesteps...")
print(f"Network: 128x128, Random opponent each episode")
print(f"Reward: +1/-1 end-game only")

model.learn(
    total_timesteps=TOTAL_TIMESTEPS,
    callback=[callback, eval_cb],
    reset_num_timesteps=False,
)

final_path = os.path.join(CHECKPOINT_DIR, "v10_final")
model.save(final_path)
env.close()
print(f"\nDone. Final model saved to {final_path}.zip")
