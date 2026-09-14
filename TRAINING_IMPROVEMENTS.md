# RL Training Improvements (v2)

## Key Issues Fixed

### 1. **Sparse Rewards**
- **Problem**: Original model only received rewards at game end (+1 win, -1 loss), making it hard to learn
- **Fix**: Added **reward shaping** that:
  - Gives +0.05 reward per damage dealt to opponent (normalized)
  - Applies -0.02 penalty per damage taken
  - Bonus reward for winning quickly (0.2 extra if win before turn 30)

### 2. **Low Exploration**
- **Problem**: `ent_coef=0.01` was too low, causing the agent to converge to a boring strategy early
- **Fix**: Increased to `ent_coef=0.05` (5x higher) to encourage trying new card combinations

### 3. **Invalid Action Penalties**
- **Problem**: Agent wastes turns trying to buy cards it can't afford (0 gold) or don't exist
- **Fix**: 
  - Added action masking to track which cards are affordable
  - Applied -0.01 penalty for invalid actions
  - Agent learns to skip buying when it has no gold

### 4. **Training Hyperparameters**
- **Learning rate**: Increased from 3e-4 to 5e-4 for faster learning
- **Batch size**: Increased from 64 to 128 for more stable gradients
- **Epochs**: Increased from 10 to 20 to better utilize each batch of data
- **Parallel environments**: Now runs 4 parallel games (configurable) for faster data collection

### 5. **Evaluation Rotation**
- **Original**: Always evaluated against BalancedAI
- **Improved**: Rotates through all 4 opponents (Balanced, Aggressive, Economic, Champion) for better performance tracking

## Usage

### Train a new v2 model from scratch:
```bash
python hero_rl_train_v2.py
```

### Continue training existing v2 model:
```bash
python hero_rl_train_v2.py --load
```

### Train with different parallelization:
```bash
python hero_rl_train_v2.py --parallel 8  # Use 8 parallel environments
```

### Evaluate models:
```bash
# Evaluate v2 model
python hero_rl_train_v2.py --eval-only

# Compare v1 vs v2
python hero_rl_train_v2.py --eval-only
python hero_rl_train_v2.py --eval-only --eval-v1
```

## Expected Improvements

With these changes, you should see:
1. **Faster learning**: More feedback per step → faster convergence
2. **Better exploration**: Agent tries more diverse strategies
3. **Higher win rates**: 50-60% baseline should improve to 55-70%+
4. **Shorter games**: Reward bonus encourages eliminating opponents quickly
5. **Generalization**: Better performance against opponents not seen during training

## Hyperparameter Tuning Guide

If results still plateau:

### Increase Exploration Further
```python
ent_coef=0.1  # Explore even more
```

### Use Larger Batch Size
```python
batch_size=256  # Larger batch = smoother gradients
n_steps=4096   # More steps per update
```

### Curriculum Learning (Future)
Could rotate through easier → harder opponents dynamically:
- Early training: Mostly BalancedAI
- Mid training: Mix all opponents 50/50
- Late training: Focus on hardest opponents

### Better Reward Shaping
Could add:
- Combo bonuses (reward for buying synergistic cards)
- Guard bonuses (reward for protecting against opponents' damage)
- Economy bonuses (reward for efficient gold/card trades)

## Files Changed

- `hero_rl_train_v2.py` - New improved training script
- Original `hero_rl_train.py` remains unchanged for comparison
- Original trained models in `models/hero_rl_ppo.zip` (v1)
- New models saved to `models/hero_rl_ppo_v2.zip` (v2)
