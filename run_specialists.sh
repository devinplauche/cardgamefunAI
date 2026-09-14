#!/usr/bin/env bash
# How exploitable are these opponents?
#
# Every run from V15 to V21 trained against opponent_profile="random", i.e. one
# policy against a mixture of four deterministic opponents. So no measurement in
# this repo separates:
#
#   "~50-55% is as well as this game can be played from this seat"
#   "~50-55% is as well as ONE policy can play against FOUR opponents at once"
#
# A specialist trained against a single fixed profile, measured against that
# same profile, bounds the difference. The opponents are deterministic given
# state, so they are exploitable in principle; the question is by how much.
#
#   specialist >> generalist  -> the plateau is a generalization tax, the game
#                                has more room, and opponent modelling is the
#                                lever (the MCTS side already has a profile
#                                posterior that the RL side never used)
#   specialist ~= generalist  -> these opponents are not more exploitable than
#                                they are already being exploited; ~55% is what
#                                this seat and this matchup allow
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

mkdir -p models_spec logs/spec

for profile in balanced aggressive economic champion; do
  for seed in 0 1; do
    python hero_rl_train_v21.py --env v4 --opponent-profile "$profile" \
        --seed "$seed" --tag "spec_${profile}" --outdir models_spec \
        > "logs/spec/spec_${profile}_s${seed}.log" 2>&1 &
  done
done
wait
echo "specialists trained"
