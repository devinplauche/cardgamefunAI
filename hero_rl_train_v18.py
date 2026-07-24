"""Train V18: self-play from the V16 warm start.

V17 established that more steps against the four fixed heuristic profiles buy
nothing - 1.5M of them moved the needle zero. That is the expected ceiling of a
fixed opponent set: once you beat them, there is no gradient left.

Self-play removes that ceiling by making the opposition improve alongside the
agent. Starting point is V16 (the best model, ~49.8% held out), and the initial
pool holds V16 itself so the first snapshots have a real opponent to beat.

Two properties of this setup are easy to get wrong and are handled explicitly:

  - **Seats are not symmetric.** A mirror match is 60/40 to the bot seat, not
    50/50, so episodes randomize the seat. Training one seat would bake in its
    assumptions.
  - **Self-play win rate is meaningless as a progress metric.** It sits near
    50% by construction no matter how strong or weak both sides are. Progress
    is therefore measured against fixed external references - the heuristic
    profiles, greedy, and frozen V16 - never against the current opponent.
"""
import os

from sb3_contrib import MaskablePPO

from hero_rl_selfplay import SelfPlayEnv, policy_win_rate
from stable_baselines3.common.callbacks import BaseCallback

TOTAL_TIMESTEPS = 1_500_000
SNAPSHOT_EVERY = 100_000
POOL_LIMIT = 8
CHECKPOINT_DIR = "models_v18"
EVAL_SEED_BASE = 100000
EVAL_EPISODES = 150
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

BASE_MODEL = "models_v16/v16_final"


class SelfPlayCallback(BaseCallback):
    """Snapshot into the opponent pool, then measure against fixed references.

    Snapshots are loaded back from disk rather than deep-copied in memory, so
    the frozen opponent cannot share parameters with the live model and drift
    as training continues.
    """

    def __init__(self, env, freq, save_dir, verbose=0):
        super().__init__(verbose)
        self.env = env
        self.freq = freq
        self.save_dir = save_dir
        self.best = 0.0

    def _on_step(self):
        if self.n_calls % self.freq != 0:
            return True

        path = os.path.join(self.save_dir, f"v18_{self.n_calls}")
        self.model.save(path)
        frozen = MaskablePPO.load(path)
        self.env.opponent_pool.append(frozen)
        if len(self.env.opponent_pool) > POOL_LIMIT:
            # Keep the original V16 anchor plus the most recent snapshots, so
            # the pool cannot drift away from a known reference entirely.
            self.env.opponent_pool[:] = (self.env.opponent_pool[:1]
                                         + self.env.opponent_pool[-(POOL_LIMIT - 1):])

        vs_heur = policy_win_rate(self.model, n=EVAL_EPISODES, base=EVAL_SEED_BASE)
        vs_v16 = policy_win_rate(self.model, n=60, base=EVAL_SEED_BASE,
                                 opponent_model=self.base_snapshot)
        flag = ""
        if vs_heur > self.best:
            self.best = vs_heur
            self.model.save(os.path.join(self.save_dir, "v18_best"))
            flag = "  <- best"
        print(f"  Step {self.n_calls}: vs-heuristics {vs_heur:.1%}  "
              f"vs-V16 {vs_v16:.1%}  pool={len(self.env.opponent_pool)}{flag}",
              flush=True)
        return True


base_snapshot = MaskablePPO.load(BASE_MODEL)
env = SelfPlayEnv(opponent_pool=[MaskablePPO.load(BASE_MODEL)], random_seat=True,
                  opponent_profile="random", fire_gem_penalty=-0.01)

model = MaskablePPO.load(BASE_MODEL, env=env)
model.learning_rate = 1e-4
model.ent_coef = 0.005

callback = SelfPlayCallback(env, SNAPSHOT_EVERY, CHECKPOINT_DIR)
callback.base_snapshot = base_snapshot

print(f"V18: self-play from {BASE_MODEL}, {TOTAL_TIMESTEPS} steps")
print(f"  Snapshot every {SNAPSHOT_EVERY}, pool capped at {POOL_LIMIT}, seats randomized")
print("  References: greedy 37.5% / V16 48.0% vs heuristics (eval seeds)")
print()

model.learn(total_timesteps=TOTAL_TIMESTEPS, callback=[callback],
            reset_num_timesteps=False)

model.save(os.path.join(CHECKPOINT_DIR, "v18_final"))
final = policy_win_rate(model, n=300, base=EVAL_SEED_BASE)
print(f"\nFinal vs heuristics: {final:.1%}   Best seen: {callback.best:.1%}")
print(f"Saved to {CHECKPOINT_DIR}/v18_final.zip and v18_best.zip")
env.close()
