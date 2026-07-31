#!/usr/bin/env bash
# Observation-repair ablation, 3 arms x 3 training seeds, run concurrently.
#
#   A  v3 env            control; reproduces the V19/V20 recipe
#   B  v4 env            observation repair only (faction, ally text, ally-live,
#                        faction concentration, sacrifice keys, opponent deck,
#                        choice candidates)
#   C  v4 env + PBRS     B plus potential-based HP-margin shaping
#
# Three seeds per arm because every RL number in BASELINE.md from V15 on is a
# single run reported as a point estimate, and the V17 section is a worked
# example of what that costs.
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

mkdir -p models_v21 logs/v21

for seed in 0 1 2; do
  python hero_rl_train_v21.py --env v3 --seed "$seed" \
      --tag v21a_v3 --outdir models_v21 > "logs/v21/v21a_v3_s${seed}.log" 2>&1 &
  python hero_rl_train_v21.py --env v4 --seed "$seed" \
      --tag v21b_obs --outdir models_v21 > "logs/v21/v21b_obs_s${seed}.log" 2>&1 &
  python hero_rl_train_v21.py --env v4 --shaping 0.5 --seed "$seed" \
      --tag v21c_pbrs --outdir models_v21 > "logs/v21/v21c_pbrs_s${seed}.log" 2>&1 &
done

wait
echo "ablation complete"
