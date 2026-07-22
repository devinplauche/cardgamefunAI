"""Improved training with better rewards, action masking, and curriculum learning."""

import argparse
import os
import sys
import numpy as np
from pathlib import Path
from collections import Counter

from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

from hero_engine import load_hero_cards, HRGame, HRPlayer, HRMarket, buy_card
from hero_ai import (
    BalancedAI, AggressiveAI, EconomicAI, ChampionAI,
    play_all_playable, attack_weakest,
)
from hero_rl_env import HeroRealmsEnv


OPPONENT_KEY_MAP = {
    "BalancedAI": "balanced",
    "AggressiveAI": "aggressive",
    "EconomicAI": "economic",
    "ChampionAI": "champion",
}


CARDS_PATH = Path("data/hero_realms_cards.json")
MODEL_PATH = Path("models/hero_rl_ppo_v2")
LOG_PATH = "logs/hero_rl_v2"
os.makedirs("models", exist_ok=True)
os.makedirs(LOG_PATH, exist_ok=True)


class ImprovedHeroRealmsEnv(HeroRealmsEnv):
    """Enhanced environment with action masking and reward shaping."""

    def __init__(self, cards, render_mode=None, max_steps=500, opponent_difficulty="balanced"):
        super().__init__(cards, render_mode, max_steps, opponent_profile=opponent_difficulty)
        self.opponent_difficulty = opponent_difficulty
        self.agent_last_hp = 50
        self.opponent_last_hp = 50

    def _get_action_mask(self):
        """Return binary mask for valid actions (can afford to buy)."""
        p = self.agent
        mask = np.zeros(7, dtype=np.int8)
        
        # Actions 0-4: buy from market
        for i in range(5):
            card = self.market.row[i]
            if card and card.cost <= p.gold:
                mask[i] = 1

        # Action 5: buy Fire Gem side pile
        if p.gold >= 2 and self.market.can_buy_fire_gem():
            mask[5] = 1
        
        # Action 6: always valid (do nothing/pass)
        mask[6] = 1
        return mask

    def step(self, action):
        """Enhanced step with reward shaping and action masking."""
        self.steps_taken += 1
        reward = 0.0
        p = self.agent
        o = self.opponent
        
        # Penalize invalid actions (wastes gold/turn)
        action_mask = self._get_action_mask()
        if action_mask[action] == 0:
            reward -= 0.01

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

        # Reward shaping: encourage dealing damage and staying alive
        opp_damage_taken = self.opponent_last_hp - o.hp
        if opp_damage_taken > 0:
            reward += 0.05 * min(opp_damage_taken / 10.0, 1.0)
        
        agent_damage_taken = self.agent_last_hp - p.hp
        if agent_damage_taken > 0:
            reward -= 0.02 * min(agent_damage_taken / 10.0, 1.0)
        
        self.agent_last_hp = p.hp
        self.opponent_last_hp = o.hp

        done = self.winner is not None
        if done:
            win_reward = 1.0 if self.winner == self.agent.name else -1.0
            turn_bonus = max(0.2 * (30.0 - self.turn) / 30.0, 0.0)
            reward = win_reward + turn_bonus

        truncated = self.steps_taken >= self.max_steps and not done

        return self._get_obs(), reward, done, truncated, {
            "action_mask": self._get_action_mask() if not done else np.ones(7)
        }

    def reset(self, seed=None, options=None):
        """Reset with curriculum learning opponent."""
        obs, info = super().reset(seed, options)
        self.agent_last_hp = self.agent.hp
        self.opponent_last_hp = self.opponent.hp
        return obs, info


def make_env(cards, rank=0, opponent_difficulty="balanced"):
    """Create environment with curriculum learning."""
    def _init():
        env = ImprovedHeroRealmsEnv(
            cards, 
            opponent_difficulty=opponent_difficulty,
            max_steps=500,
        )
        env = Monitor(env, os.path.join(LOG_PATH, f"run_{rank}"))
        return env
    return _init


class WinRateCallback(BaseCallback):
    """Track win rates against all AI opponents."""

    def __init__(self, eval_cards, eval_freq=5000, n_eval_episodes=50, verbose=0):
        super().__init__(verbose)
        self.eval_cards = eval_cards
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.best_mean_reward = -np.inf
        self.opponent_rotations = ["BalancedAI", "AggressiveAI", "EconomicAI", "ChampionAI"]
        self.current_opponent = 0

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            # Rotate through opponents
            opponent = self.opponent_rotations[self.current_opponent % len(self.opponent_rotations)]
            self.current_opponent += 1
            
            opp_key = OPPONENT_KEY_MAP[opponent]
            env = HeroRealmsEnv(self.eval_cards, opponent_profile=opp_key)
            wins = 0
            for _ in range(self.n_eval_episodes):
                obs, _ = env.reset()
                done = False
                while not done:
                    action, _ = self.model.predict(obs, deterministic=True)
                    obs, _, done, truncated, _ = env.step(action)
                    if truncated:
                        break
                if env.winner == env.agent.name:
                    wins += 1
            wr = wins / self.n_eval_episodes
            print(f"\n[Eval @ {self.n_calls}] Win rate vs {opponent}: {wr:.2%}")
            env.close()
        return True


def train_v2(cards, total_timesteps=200_000, num_envs=4):
    """Train with multiple improvements."""
    print(f"Training PPO v2 for {total_timesteps} timesteps with {num_envs} parallel envs...")
    
    # Use multiple parallel environments
    opponent_cycle = ["balanced", "aggressive", "economic", "champion"]
    env = DummyVecEnv([
        make_env(cards, i, opponent_cycle[i % len(opponent_cycle)])
        for i in range(num_envs)
    ])

    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=5e-4,  # Slightly higher LR
        n_steps=2048,
        batch_size=128,  # Larger batch for stability
        n_epochs=20,  # More epochs to process data better
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.05,  # HIGHER entropy for more exploration
        vf_coef=0.5,  # Value function weight
        max_grad_norm=0.5,
        verbose=1,
    )

    win_rate_cb = WinRateCallback(cards, eval_freq=5000, n_eval_episodes=50)
    checkpoint_cb = CheckpointCallback(
        save_freq=25000, save_path="models/", name_prefix="hero_rl_ppo_v2"
    )

    model.learn(
        total_timesteps=total_timesteps,
        callback=[win_rate_cb, checkpoint_cb],
        progress_bar=True,
    )

    model.save(str(MODEL_PATH))
    print(f"Model saved to {MODEL_PATH}")
    env.close()
    return model


def continue_train_v2(cards, total_timesteps=200_000, num_envs=4):
    """Continue training an existing model."""
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        print(f"No saved model at {model_path}, starting fresh.")
        return train_v2(cards, total_timesteps, num_envs)

    print(f"Loading model from {model_path}, training for {total_timesteps} more...")
    opponent_cycle = ["balanced", "aggressive", "economic", "champion"]
    env = DummyVecEnv([
        make_env(cards, i, opponent_cycle[i % len(opponent_cycle)])
        for i in range(num_envs)
    ])
    model = PPO.load(model_path, env=env)

    # Update learning rate for continued training (decay)
    model.learning_rate = 3e-4

    win_rate_cb = WinRateCallback(cards, eval_freq=5000, n_eval_episodes=50)

    model.learn(
        total_timesteps=total_timesteps,
        callback=[win_rate_cb],
        reset_num_timesteps=False,
        progress_bar=True,
    )

    model.save(str(MODEL_PATH))
    print(f"Model updated at {MODEL_PATH}")
    env.close()
    return model


def evaluate(cards, model_path=None, n_games=200):
    """Evaluate model against all opponents."""
    if model_path is None:
        model_path = str(MODEL_PATH) + ".zip"
    
    if not os.path.exists(model_path):
        print(f"No saved model at {model_path}. Train first.")
        return

    from stable_baselines3 import PPO
    model = PPO.load(model_path)

    opponents = {
        "BalancedAI": (BalancedAI.play, BalancedAI.buy, BalancedAI.attack),
        "AggressiveAI": (AggressiveAI.play, AggressiveAI.buy, AggressiveAI.attack),
        "EconomicAI": (EconomicAI.play, EconomicAI.buy, EconomicAI.attack),
        "ChampionAI": (ChampionAI.play, ChampionAI.buy, ChampionAI.attack),
    }

    for opp_name, (play_fn, buy_fn, attack_fn) in opponents.items():
        opp_key = OPPONENT_KEY_MAP[opp_name]
        env = HeroRealmsEnv(cards, opponent_profile=opp_key)
        wins = 0
        agent_turns = []
        buy_log = []

        for g in range(n_games):
            obs, _ = env.reset()
            done = False
            game_buys = []
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                if action < 5:
                    card = env.market.row[action]
                    if card:
                        game_buys.append(card.name)
                elif action == 5:
                    game_buys.append("Fire Gem")
                obs, _, done, truncated, _ = env.step(action)
                if truncated:
                    break
            if env.winner == env.agent.name:
                wins += 1
                agent_turns.append(env.turn)
                buy_log.extend(game_buys)
            env.close()

        wr = wins / n_games
        avg_turns = np.mean(agent_turns) if agent_turns else 0
        print(f"\n{'='*50}")
        print(f"RL Agent vs {opp_name}")
        print(f"  Win rate: {wr:.1%} ({wins}/{n_games})")
        print(f"  Avg turns (wins): {avg_turns:.1f}")

        if buy_log:
            counts = Counter(buy_log)
            print(f"  Top 10 most-bought cards (in wins):")
            for name, cnt in counts.most_common(10):
                print(f"    {name}: {cnt}")

    print(f"\n{'='*50}")
    print("Done evaluating.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--load", action="store_true", help="Continue training from v2 model")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate")
    parser.add_argument("--timesteps", type=int, default=200_000, help="Total timesteps")
    parser.add_argument("--parallel", type=int, default=4, help="Number of parallel envs")
    parser.add_argument("--eval-v1", action="store_true", help="Evaluate original v1 model")
    args = parser.parse_args()

    cards = load_hero_cards(str(CARDS_PATH))
    print(f"Loaded {len(cards)} cards from {CARDS_PATH}")

    if args.eval_only:
        if args.eval_v1:
            print("\nEvaluating V1 model...")
            evaluate(cards, "models/hero_rl_ppo.zip")
        else:
            evaluate(cards)
    elif args.load:
        model = continue_train_v2(cards, args.timesteps, args.parallel)
        evaluate(cards)
    else:
        model = train_v2(cards, args.timesteps, args.parallel)
        evaluate(cards)
