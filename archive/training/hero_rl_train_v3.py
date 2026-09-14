"""V3 RL Training - Optimized hyperparameters for 60%+ win rate target."""

import argparse
import os
import numpy as np
from pathlib import Path
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

from hero_engine import load_hero_cards, buy_card
from hero_rl_env import HeroRealmsEnv


CARDS_PATH = Path("data/hero_realms_cards.json")
MODEL_PATH = Path("models/hero_rl_ppo_v3")
LOG_PATH = "logs/hero_rl_v3"
os.makedirs("models", exist_ok=True)
os.makedirs(LOG_PATH, exist_ok=True)


class ImprovedHeroRealmsEnv(HeroRealmsEnv):
    """Enhanced environment with better reward shaping for V3."""

    def __init__(self, cards, render_mode=None, max_steps=500):
        super().__init__(cards, render_mode, max_steps)
        self.agent_last_hp = 50
        self.opponent_last_hp = 50

    def _get_action_mask(self):
        """Return binary mask for valid actions."""
        p = self.agent
        mask = np.zeros(7, dtype=np.int8)
        
        for i in range(5):
            card = self.market.row[i]
            if card and card.cost <= p.gold:
                mask[i] = 1

        # Action 5: buy Fire Gem side pile
        if p.gold >= 2 and self.market.can_buy_fire_gem():
            mask[5] = 1
        
        mask[6] = 1  # Pass always valid
        return mask

    def step(self, action):
        """Enhanced step with improved reward shaping for V3."""
        self.steps_taken += 1
        reward = 0.0
        p = self.agent
        o = self.opponent
        
        action_mask = self._get_action_mask()
        if action_mask[action] == 0:
            reward -= 0.02  # Stronger penalty for invalid actions

        if action <= 5:
            bought = buy_card(p, self.market, action)
            if not bought:
                self._resolve_turn()
            else:
                can_buy = False
                if p.gold > 0:
                    for c in self.market.row_cards():
                        if c and c.cost <= p.gold:
                            can_buy = True
                            break
                    if not can_buy and p.gold >= 2 and self.market.can_buy_fire_gem():
                        can_buy = True
                if not can_buy:
                    self._resolve_turn()
        else:
            self._resolve_turn()

        # V3 IMPROVED REWARD SHAPING
        # More granular feedback on damage dealt/taken
        opp_damage_taken = self.opponent_last_hp - o.hp
        if opp_damage_taken > 0:
            reward += 0.08 * min(opp_damage_taken / 10.0, 1.0)  # Increased from 0.05
        
        agent_damage_taken = self.agent_last_hp - p.hp
        if agent_damage_taken > 0:
            reward -= 0.04 * min(agent_damage_taken / 10.0, 1.0)  # Increased penalty
        
        self.agent_last_hp = p.hp
        self.opponent_last_hp = o.hp

        done = self.winner is not None
        if done:
            # Win bonus with turn completion bonus (reward for quick wins)
            win_reward = 1.2 if self.winner == self.agent.name else -1.2
            turn_bonus = max(0.3 * (30.0 - self.turn) / 30.0, 0.0)  # Increased from 0.2
            reward = win_reward + turn_bonus

        truncated = self.steps_taken >= self.max_steps and not done

        return self._get_obs(), reward, done, truncated, {
            "action_mask": self._get_action_mask() if not done else np.ones(7)
        }

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed, options)
        self.agent_last_hp = self.agent.hp
        self.opponent_last_hp = self.opponent.hp
        return obs, info


def make_env(cards, rank=0):
    """Create environment wrapper."""
    def _init():
        env = ImprovedHeroRealmsEnv(cards, max_steps=500)
        env = Monitor(env, os.path.join(LOG_PATH, f"run_{rank}"))
        return env
    return _init


class WinRateCallback(BaseCallback):
    """Track win rates against all AI opponents."""

    def __init__(self, eval_cards, eval_freq=5000, n_eval_episodes=50):
        super().__init__()
        self.eval_cards = eval_cards
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.opponent_rotations = ["BalancedAI", "AggressiveAI", "EconomicAI", "ChampionAI"]
        self.current_opponent = 0

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            opponent = self.opponent_rotations[self.current_opponent % len(self.opponent_rotations)]
            self.current_opponent += 1
            
            env = HeroRealmsEnv(self.eval_cards)
            wins = 0
            for _ in range(self.n_eval_episodes):
                obs, _ = env.reset()
                done = False
                while not done:
                    action, _ = self.model.predict(obs, deterministic=True)
                    obs, _, done, truncated, _ = env.step(action)
                    done = done or truncated
                
                if env.winner == env.agent.name:
                    wins += 1
            
            win_rate = wins / self.n_eval_episodes
            print(f"\n[Eval @ {self.num_timesteps}] Win rate vs {opponent}: {win_rate*100:.1f}%")


def train_v3(timesteps=450000, parallel_envs=4, load=False):
    """Train V3 model with improved hyperparameters targeting 60%+ win rate."""
    print(f"Loading cards...")
    cards = load_hero_cards(str(CARDS_PATH))
    
    print(f"Training PPO v3 for {timesteps} timesteps with {parallel_envs} parallel envs...")
    
    # Create parallel environments
    env_fns = [make_env(cards, rank=i) for i in range(parallel_envs)]
    vec_env = SubprocVecEnv(env_fns)
    
    model_path = str(MODEL_PATH)
    
    # V3 IMPROVED HYPERPARAMETERS for 60%+ target
    if load and os.path.exists(model_path + ".zip"):
        print(f"Loading model from {model_path}.zip")
        model = PPO.load(model_path, env=vec_env)
    else:
        model = PPO(
            policy="MlpPolicy",
            env=vec_env,
            learning_rate=8e-4,  # V3: Increased from 5e-4 to 8e-4
            n_steps=8192,
            batch_size=256,  # V3: Increased from 128 to 256
            n_epochs=30,  # V3: Increased from 20 to 30
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.10,  # V3: Increased from 0.05 to 0.10 for more exploration
            vf_coef=0.5,
            max_grad_norm=0.5,
            use_sde=False,
            verbose=1
        )
    
    checkpoint_callback = CheckpointCallback(
        save_freq=25000,
        save_path="models/",
        name_prefix="hero_rl_ppo_v3_checkpoint"
    )
    
    eval_callback = WinRateCallback(
        eval_cards=cards,
        eval_freq=5000,
        n_eval_episodes=50
    )
    
    model.learn(
        total_timesteps=timesteps,
        callback=[checkpoint_callback, eval_callback],
        progress_bar=True
    )
    
    model.save(model_path)
    print(f"Model saved to {model_path}.zip")
    
    # Final comprehensive evaluation
    print("\n" + "="*60)
    print("FINAL EVALUATION - V3 Model (60%+ Target)")
    print("="*60)
    
    from hero_rl_env import HeroRealmsEnv
    
    opponents = ["BalancedAI", "AggressiveAI", "EconomicAI", "ChampionAI"]
    results = {}
    
    for opponent_name in opponents:
        env = HeroRealmsEnv(cards)
        wins = 0
        for _ in range(200):
            obs, _ = env.reset()
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, truncated, _ = env.step(action)
                done = done or truncated
            
            if env.winner == env.agent.name:
                wins += 1
        
        win_rate = wins / 200
        results[opponent_name] = win_rate
        status = "✅" if win_rate >= 0.60 else "⚠️"
        print(f"{status} Win rate vs {opponent_name}: {win_rate*100:.1f}% ({wins}/200)")
    
    avg_wr = np.mean(list(results.values()))
    print(f"\n{'='*60}")
    print(f"Average win rate: {avg_wr*100:.1f}%")
    print(f"Target achieved: {'✅ YES (60%+)' if avg_wr >= 0.60 else '⚠️ PARTIAL - Continue training'}")
    print(f"{'='*60}\n")
    
    return model


def continue_train_v3(additional_timesteps=100000, parallel_envs=4):
    """Continue training existing V3 model."""
    return train_v3(timesteps=additional_timesteps, parallel_envs=parallel_envs, load=True)


def eval_only():
    """Evaluate trained V3 model."""
    print("Loading model and cards...")
    cards = load_hero_cards(str(CARDS_PATH))
    model_path = str(MODEL_PATH)
    
    if not os.path.exists(model_path + ".zip"):
        print(f"Model not found at {model_path}.zip")
        return
    
    model = PPO.load(model_path)
    
    print("\n" + "="*60)
    print("V3 Model Evaluation")
    print("="*60)
    
    from hero_rl_env import HeroRealmsEnv
    
    opponents = ["BalancedAI", "AggressiveAI", "EconomicAI", "ChampionAI"]
    results = {}
    
    for opponent_name in opponents:
        env = HeroRealmsEnv(cards)
        wins = 0
        for _ in range(200):
            obs, _ = env.reset()
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, truncated, _ = env.step(action)
                done = done or truncated
            
            if env.winner == env.agent.name:
                wins += 1
        
        win_rate = wins / 200
        results[opponent_name] = win_rate
        status = "✅" if win_rate >= 0.60 else "⚠️"
        print(f"{status} Win rate vs {opponent_name}: {win_rate*100:.1f}% ({wins}/200)")
    
    avg_wr = np.mean(list(results.values()))
    print(f"\nAverage win rate: {avg_wr*100:.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V3 RL Training for Hero Realms")
    parser.add_argument("--timesteps", type=int, default=450000, help="Training timesteps")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel environments")
    parser.add_argument("--load", action="store_true", help="Load and continue training")
    parser.add_argument("--eval-only", action="store_true", help="Evaluation only")
    
    args = parser.parse_args()
    
    if args.eval_only:
        eval_only()
    elif args.load:
        continue_train_v3(args.timesteps, args.parallel)
    else:
        train_v3(args.timesteps, args.parallel)
