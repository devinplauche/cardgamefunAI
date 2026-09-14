"""Train V9: longer training, intermediate rewards, tuned hyperparameters."""

import argparse, os, time, random
import numpy as np
from pathlib import Path
from collections import Counter
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from hero_engine import load_hero_cards
from hero_rl_env import HeroRealmsEnv

CARDS_PATH = Path("data/hero_realms_cards.json")
MODEL_PATH = Path("models/hero_rl_ppo_v9")
LOG_PATH = "logs/hero_rl_v9"
os.makedirs("models", exist_ok=True)
os.makedirs(LOG_PATH, exist_ok=True)

PROFILES = {
    "balanced": {"name": "BalancedAI"},
    "aggressive": {"name": "AggressiveAI"},
    "economic": {"name": "EconomicAI"},
    "champion": {"name": "ChampionAI"},
}

import gymnasium as gym
from gymnasium import spaces

class RandomOpponentWrapper(gym.Wrapper):
    """Randomize opponent profile each reset."""
    PROFILES = ["balanced", "aggressive", "economic", "champion"]
    def reset(self, **kwargs):
        profile = np.random.choice(self.PROFILES)
        self.env.set_opponent_profile(profile)
        return super().reset(**kwargs)

def make_env(cards, profile="balanced", rank=0):
    def _init():
        env = HeroRealmsEnv(cards, opponent_profile=profile)
        env = RandomOpponentWrapper(env)
        env = Monitor(env, os.path.join(LOG_PATH, f"run_{rank}"))
        return env
    return _init

def train(cards, total_timesteps=1_000_000):
    print(f"Training V9 PPO for {total_timesteps} timesteps...")
    # Train against random opponent each episode for robustness
    env = DummyVecEnv([make_env(cards, profile=np.random.choice(list(PROFILES.keys())), rank=0)])
    
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=128,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        vf_coef=0.5,
        max_grad_norm=0.5,
        verbose=1,
    )

    checkpoint_cb = CheckpointCallback(
        save_freq=50000, save_path="models/", name_prefix="hero_rl_ppo_v9"
    )

    model.learn(
        total_timesteps=total_timesteps,
        callback=[checkpoint_cb],
        progress_bar=True,
    )

    model.save(str(MODEL_PATH))
    print(f"Model saved to {MODEL_PATH}")
    env.close()
    return model


def evaluate(cards, n_games=200):
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        print(f"No model at {model_path}")
        return

    model = PPO.load(model_path)
    print(f"\n{'='*60}")
    print(f"V9 Evaluation ({model.num_timesteps} timesteps)")
    print(f"{'='*60}")

    all_buys = []
    for prof_key, prof_info in PROFILES.items():
        wins = 0
        agent_turns = []
        buy_log = []
        for g in range(n_games):
            env = HeroRealmsEnv(cards, opponent_profile=prof_key)
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
        avg_t = np.mean(agent_turns) if agent_turns else 0
        print(f"\n  vs {prof_info['name']:<15}: {wr:.1%} ({wins}/{n_games}), avg turns: {avg_t:.1f}")
        all_buys.extend(buy_log)

        if buy_log:
            counts = Counter(buy_log)
            print(f"  Top buys in wins:")
            for name, cnt in counts.most_common(8):
                print(f"    {name}: {cnt}")

    print(f"\n{'='*60}")
    print("Aggregate top buys (all winning games):")
    if all_buys:
        counts = Counter(all_buys)
        for name, cnt in counts.most_common(15):
            print(f"  {name}: {cnt}")
    print(f"{'='*60}")


def analyze_buy_patterns(cards, n_games=500):
    model_path = str(MODEL_PATH) + ".zip"
    if not os.path.exists(model_path):
        return

    model = PPO.load(model_path)
    agent_buys = Counter()

    for g in range(n_games):
        env = HeroRealmsEnv(cards)
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
    print(f"\n{'='*60}")
    print(f"V9 Buy Patterns ({n_games} games, {total} purchases)")
    print(f"{'Rank':<5} {'Card':<30} {'Count':<8} {'% of Buys':<10} {'Cost':<6}")
    print("-" * 60)
    for rank, (name, cnt) in enumerate(agent_buys.most_common(20), 1):
        pct = cnt / total * 100
        print(f"{rank:<5} {name:<30} {cnt:<8} {pct:<10.1f}")
    return agent_buys


def quick_eval(model_path, cards, profile="balanced", n=200):
    """Evaluate a specific model file."""
    model = PPO.load(model_path)
    wins = 0
    for g in range(n):
        env = HeroRealmsEnv(cards, opponent_profile=profile)
        obs, _ = env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, _, done, truncated, _ = env.step(action)
            if truncated:
                break
        if env.winner == env.agent.name:
            wins += 1
        env.close()
    return wins / n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--load", action="store_true", help="Continue training")
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--checkpoint", type=str, default="", help="Specific checkpoint to evaluate")
    args = parser.parse_args()

    cards = load_hero_cards(str(CARDS_PATH))
    print(f"Loaded {len(cards)} cards from {CARDS_PATH}")

    if args.eval_only:
        if args.checkpoint:
            for prof in PROFILES:
                wr = quick_eval(args.checkpoint, cards, profile=prof)
                print(f"  {args.checkpoint} vs {prof}: {wr:.1%}")
        else:
            evaluate(cards)
            if args.analyze:
                analyze_buy_patterns(cards)
    elif args.load:
        model_path = str(MODEL_PATH) + ".zip"
        if os.path.exists(model_path):
            print(f"Loading {model_path}, continuing for {args.timesteps}...")
            env = DummyVecEnv([make_env(cards, rank=0)])
            model = PPO.load(model_path, env=env)
            model.learn(total_timesteps=args.timesteps, reset_num_timesteps=False, progress_bar=True)
            model.save(str(MODEL_PATH))
            env.close()
        evaluate(cards)
    else:
        train(cards, args.timesteps)
        evaluate(cards)
        analyze_buy_patterns(cards)
