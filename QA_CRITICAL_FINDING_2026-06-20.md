> **SUPERSEDED (2026-07-22).** The per-opponent win rates below were produced
> with a broken evaluation harness: `HeroRealmsEnv` ignored the requested
> `opponent_profile` and always played BalancedAI, so all four columns are the
> same matchup relabelled. See [BASELINE.md](BASELINE.md) for verified numbers.

# Critical QA Finding: Opponent Rotation Was Not Active

Date: 2026-06-20

## Finding
The RL environment always used BalancedAI behavior in opponent turns, even when training and evaluation logs reported other opponent names.

Affected areas:
- Training callback labels in hero_rl_train_v2.py
- Evaluation loop opponent labels in hero_rl_train_v2.py
- Opponent turn logic in hero_rl_env.py

## Root Cause
hero_rl_env.py hard-coded:
- play_all_playable
- buy_balanced
- attack_weakest

There was no strategy profile switch for AggressiveAI, EconomicAI, or ChampionAI.

## Fix Applied
1. Added explicit opponent profiles in hero_rl_env.py:
- balanced
- aggressive
- economic
- champion

2. Extended HeroRealmsEnv constructor with opponent_profile parameter.

3. Updated opponent turn resolution to call profile-specific:
- play
- buy
- expend
- attack

4. Updated hero_rl_train_v2.py:
- true opponent rotation across parallel envs during training
- callback eval now instantiates env with the requested profile
- evaluate now runs each opponent profile correctly

## Post-Fix Corrected Evaluation (Current v2 model)
- BalancedAI: 34.0% (68/200)
- AggressiveAI: 46.5% (93/200)
- EconomicAI: 38.5% (77/200)
- ChampionAI: 49.0% (98/200)

Average: 42.0%

## Impact
Previous cross-opponent results were optimistic and not strictly valid as multi-opponent benchmarks.
This fix makes future training and evaluations trustworthy.

## Current Action
A fresh training run with true multi-opponent rotation is in progress:
- hero_rl_train_v2.py --timesteps 400000 --parallel 4
