"""Train a PPO agent to learn optimal buy strategies in Hero Realms.

Usage:
    python hero_rl_train.py              # train from scratch
    python hero_rl_train.py --load       # continue training from saved model
    python hero_rl_train.py --eval-only  # just evaluate saved model vs heuristics
"""

import argparse
import os
import sys
import time
import numpy as np
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback, EvalCallback
from stable_baselines3.common.monitor import Monitor

from hero_engine import load_hero_cards, HRGame, HRPlayer, HRMarket
from hero_ai import (
    BalancedAI, AggressiveAI, EconomicAI, ChampionAI,
    play_all_playable, attack_weakest,
)
from hero_rl_env import HeroRealmsEnv


CARDS_PATH = Path("data/hero_realms_cards.json")
MODEL_PATH = Path("models/hero_rl_ppo")
LOG_PATH = "logs/hero_rl"
os.makedirs("models", exist_ok=True)
os.makedirs("logs", exist_ok=True)


def make_env(cards, rank=0):
    def _init():
        env = HeroRealmsEnv(cards)
        env = Monitor(env, os.path.join(LOG_PATH, f"run_{rank}"))
        return env
    return _init


class WinRateCallback(BaseCallback):
    """Log rolling win rate against heuristic opponents."""

    def __init__(self, eval_cards, eval_freq=5000, n_eval_episodes=50, verbose=0):
        super().__init__(verbose)
        self.eval_cards = eval_cards
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.win_rates = []

    def _on_step(self):
        if self.n_calls % self.eval_freq == 0:
            env = HeroRealmsEnv(self.eval_cards)
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
            self.win_rates.append((self.n_calls, wr))
            print(f"\n[Eval @ {self.n_calls}] Win rate vs BalancedAI: {wr:.2%}")
            env.close()
        return True


def train(cards, total_timesteps=200_000):
    print(f"Training PPO for {total_timesteps} timesteps...")
    env = DummyVecEnv([make_env(cards, 0)])

    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        verbose=1,
    )

    win_rate_cb = WinRateCallback(cards, eval_freq=5000, n_eval_episodes=50)
    checkpoint_cb = CheckpointCallback(
        save_freq=25000, save_path="models/", name_prefix="hero_rl_ppo"
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


def continue_train(cards, total_timesteps=100_000):
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        print(f"No saved model at {model_path}, starting fresh.")
        return train(cards, total_timesteps)

    print(f"Loading model from {model_path}, training for {total_timesteps} more...")
    env = DummyVecEnv([make_env(cards, 0)])
    model = PPO.load(model_path, env=env)

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


def evaluate(cards, n_games=200):
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        print(f"No saved model at {model_path}. Train first.")
        return

    model = PPO.load(model_path)

    opponents = {
        "BalancedAI": (BalancedAI.play, BalancedAI.buy, BalancedAI.attack),
        "AggressiveAI": (AggressiveAI.play, AggressiveAI.buy, AggressiveAI.attack),
        "EconomicAI": (EconomicAI.play, EconomicAI.buy, EconomicAI.attack),
        "ChampionAI": (ChampionAI.play, ChampionAI.buy, ChampionAI.attack),
    }

    for opp_name, (play_fn, buy_fn, attack_fn) in opponents.items():
        env = HeroRealmsEnv(cards)
        wins = 0
        total_turns = 0
        agent_turns = []
        buy_log = []  # track which cards the agent bought

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

        # Most-purchased cards
        if buy_log:
            from collections import Counter
            counts = Counter(buy_log)
            print(f"  Top 10 most-bought cards (in wins):")
            for name, cnt in counts.most_common(10):
                print(f"    {name}: {cnt}")

    print(f"\n{'='*50}")
    print("Done evaluating.")


def analyze_buy_patterns(cards, n_games=500):
    """Deep analysis: track what RL agent buys vs what balanced heuristic buys."""
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        print(f"No saved model at {model_path}. Train first.")
        return

    model = PPO.load(model_path)

    env = HeroRealmsEnv(cards)
    from collections import Counter
    agent_buys = Counter()

    for g in range(n_games):
        obs, _ = env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            if action < 5:
                card = env.market.row[action]
                if card:
                    agent_buys[card.name] += 1
            elif action == 5:
                agent_buys["Fire Gem"] += 1
            obs, _, done, truncated, _ = env.step(action)
            if truncated:
                break
        env.close()

    total = sum(agent_buys.values())
    print(f"\n{'='*50}")
    print(f"RL Agent Buy Patterns ({n_games} games, {total} total purchases)")
    print(f"{'Rank':<5} {'Card':<30} {'Count':<8} {'% of Buys':<10} {'Cost':<6}")
    print("-" * 60)
    for rank, (name, cnt) in enumerate(agent_buys.most_common(20), 1):
        pct = cnt / total * 100
        print(f"{rank:<5} {name:<30} {cnt:<8} {pct:<10.1f}")

    return agent_buys


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--load", action="store_true", help="Continue training from saved model")
    parser.add_argument("--eval-only", action="store_true", help="Skip training, only evaluate")
    parser.add_argument("--timesteps", type=int, default=200_000, help="Total training timesteps")
    parser.add_argument("--analyze", action="store_true", help="Run deep buy-pattern analysis")
    args = parser.parse_args()

    cards = load_hero_cards(str(CARDS_PATH))
    print(f"Loaded {len(cards)} cards from {CARDS_PATH}")

    if args.eval_only:
        evaluate(cards)
        if args.analyze:
            analyze_buy_patterns(cards)
    elif args.load:
        model = continue_train(cards, args.timesteps)
        evaluate(cards)
    else:
        model = train(cards, args.timesteps)
        evaluate(cards)
        analyze_buy_patterns(cards)
