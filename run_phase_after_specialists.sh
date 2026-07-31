#!/usr/bin/env bash
# Chain the remaining work so the wall-clock benchmark never shares the CPU.
#
#   1. wait for the 8 specialist training runs to land
#   2. evaluate specialists vs generalists, held-out (CPU-heavy, parallel)
#   3. only then run the game-phase A/B, which is wall-clock budgeted and would
#      be corrupted by any concurrent load
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "waiting for specialists..."
while [ "$(ls models_spec/*.json 2>/dev/null | wc -l)" -lt 8 ]; do sleep 30; done
echo "specialists done"

python hero_rl_summarize.py models_spec

echo
echo "=== held-out: specialist vs generalist, each against its own profile ==="
for profile in balanced aggressive economic champion; do
  python hero_rl_eval_masked.py --env v4 --games 300 --profile "$profile" \
      "models_spec/spec_${profile}_s0_final" "models_spec/spec_${profile}_s1_final" \
      models_v21/v21b_obs_s0_final models_v21/v21b_obs_s1_final models_v21/v21b_obs_s2_final \
      > "logs/spec/heldout_${profile}.log" 2>&1 &
done
wait
for profile in balanced aggressive economic champion; do
  echo "--- vs ${profile} (first two rows are specialists, last three generalists) ---"
  grep -E "^models_|^policy|^-{5,}" "logs/spec/heldout_${profile}.log"
done

echo
echo "=== game-phase A/B (exclusive CPU) ==="
python hero_phase_ab.py 100 60
