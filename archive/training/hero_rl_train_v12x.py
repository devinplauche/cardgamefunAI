"""Continue training V12 for 2M more steps from best checkpoint."""
import os
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from hero_engine import load_hero_cards
from hero_rl_env import HeroRealmsEnv

FIRE_GEM_PENALTY = -0.01
cards = load_hero_cards("data/hero_realms_cards.json")

TOTAL_TIMESTEPS = 2_000_000
CHECKPOINT_DIR = "models_v12x"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

class EvalCallback(BaseCallback):
    def __init__(self, eval_freq, n_episodes=200, verbose=0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.n_episodes = n_episodes

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            wins = 0
            for _ in range(self.n_episodes):
                env = HeroRealmsEnv(cards, opponent_profile="random",
                                    allow_fire_gem=True, fire_gem_penalty=FIRE_GEM_PENALTY)
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

print("Loading V12 best checkpoint (1.8M)...")
model = PPO.load("models_v12/v12_1800000.zip")
print(f"Continuing from {model.num_timesteps} timesteps")

env = HeroRealmsEnv(cards, opponent_profile="random",
                    allow_fire_gem=True, fire_gem_penalty=FIRE_GEM_PENALTY)
model.set_env(env)

class CheckpointCallback(BaseCallback):
    def __init__(self, save_freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.save_dir = save_dir

    def _on_step(self):
        if self.n_calls % self.save_freq == 0:
            path = os.path.join(self.save_dir, f"v12x_{self.n_calls}")
            self.model.save(path)
        return True

callback = CheckpointCallback(save_freq=100000, save_dir=CHECKPOINT_DIR)
eval_cb = EvalCallback(eval_freq=100000, n_episodes=200)

print(f"Training V12x for {TOTAL_TIMESTEPS} more timesteps (total ~3.8M)...")
print(f"  Fire Gem penalty: {FIRE_GEM_PENALTY}")

model.learn(
    total_timesteps=TOTAL_TIMESTEPS,
    callback=[callback, eval_cb],
    reset_num_timesteps=False,
)

final_path = os.path.join(CHECKPOINT_DIR, "v12x_final")
model.save(final_path)
env.close()
print(f"\nDone. Final model saved to {final_path}.zip")
