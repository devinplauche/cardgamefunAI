# Tests

This project uses lightweight GDScript tests for card abilities, UI behavior, and no-UI gameplay simulation.

## Run Everything

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\run_all.ps1
```

## Run in Godot

1. Open `res://tests/TestCardAbilities.gd`.
2. Attach it to an empty Node in a temporary scene and run that scene.
3. Check the output panel for pass/fail lines.

The test script calls `get_tree().quit(exit_code)`:
- `0` means all tests passed
- `1` means one or more tests failed

## No-UI Match Simulation

Use `res://tests/SimulateGameNoUI.gd` to run deterministic headless-style gameplay smoke tests without any battle UI scene.

1. Open `res://tests/SimulateGameNoUI.gd`.
2. Attach it to an empty Node in a temporary scene and run that scene.
3. Check the output panel for turn-by-turn HP logs, final winner lines, and the completed-match summary.

This simulation validates that turn flow, market purchases, card effects, and combat resolution can run end-to-end without UI node dependencies. It exits non-zero if a deterministic seed fails to produce a winner or leaves invalid gameplay state.

## Parsed Ability Validation

Use `res://tests/TestParsedAbilities.gd` to validate advanced Hero Realms parsing and runtime behavior.

1. Open `res://tests/TestParsedAbilities.gd`.
2. Attach it to an empty Node in a temporary scene and run that scene.
3. Check the output panel for pass/fail lines.

Optional CLI run:

```bash
"/c/Users/devinsGamingPC/Downloads/Godot_v4.5.1-stable_win64.exe/Godot_v4.5.1-stable_win64_console.exe" --headless --path . --scene res://tests/TestParsedAbilitiesRunner.tscn
```

## Player Choice Validation

Use `res://tests/TestPlayerChoices.gd` to validate popup-choice request and resolution behavior for manual discard, sacrifice, and effect-branch choices.

```bash
"/c/Users/devinsGamingPC/Downloads/Godot_v4.5.1-stable_win64.exe/Godot_v4.5.1-stable_win64_console.exe" --headless --path . --scene res://tests/TestPlayerChoicesRunner.tscn
```

## AI Strategy Benchmark

### Pure-Python benchmark (no Godot required)

`tests/benchmark_strategies.py` is a self-contained Python port of the GDScript
benchmark. It uses `cards/marketplace.json` and the same starter deck, strategy
logic, and seeding scheme as `AIBenchmark.gd`, so results are directly comparable.
It runs in under 5 seconds for the default 50 games/pair and requires no external
dependencies beyond Python 3.8+.

```bash
# Full run (50 games/pair, ~3 s)
python3 tests/benchmark_strategies.py

# Faster smoke-test (10 games/pair)
python3 tests/benchmark_strategies.py --games 10

# Export results to CSV
python3 tests/benchmark_strategies.py --csv results.csv
```

### GDScript benchmark (requires Godot)

Use `res://tests/AIBenchmark.gd` to run a round-robin tournament that pits all
ten AI strategies (Random, Aggro, Econ, Control, Combo, Efficiency, Greedy,
Lookahead, Adaptive, Oracle) against each other and prints a ranked leaderboard with
95% confidence intervals, a head-to-head win-rate matrix, and a CSV export.

Each ordered pair of strategies plays 50 games (strategy A always goes first);
since both orderings are tested the unordered matchup is resolved over 100 games.
Results include win / loss / draw counts, a final win-rate ranking with 95%
confidence intervals, and a CSV written to `user://ai_benchmark_results.csv`.

```bash
"/c/Users/devinsGamingPC/Downloads/Godot_v4.5.1-stable_win64.exe/Godot_v4.5.1-stable_win64_console.exe" --headless --path . --scene res://tests/AIBenchmarkRunner.tscn
```

### Strategies

| Name | Card selection | Market buying |
|------|---------------|---------------|
| **Random** | Random card from hand | Random affordable offer |
| **Aggro** | Highest damage card | Offer with most `combat` value |
| **Econ** | Highest resource (gold/draw) card | Most expensive affordable offer |
| **Control** | Highest disruption card | Offer with most `opponent_discard` value |
| **Combo** | Highest faction-trigger/ally-synergy card | Offer with ally bonuses + faction match; falls back to evaluator |
| **Efficiency** | Highest sacrifice+draw value card | Offer with sacrifice and draw abilities; falls back to greedy-by-cost |
| **Greedy** | Evaluator score (single-step) | Evaluator-scored offer with lethal-urgency pass |
| **Lookahead** | Evaluator score with 2-ply look-ahead (includes market future value) | Evaluator-scored offer with lethal-urgency pass |
| **Adaptive** | Dynamic axis switching: danger→block, late→aggro, mid+champions→combo, early→greedy | Dynamic: danger→health/combat, late→combat, mid+champions→combo, early→greedy-by-cost |
| **Oracle** | Adaptive-style scoring plus follow-up lookahead, faction/utility bonuses, and stronger tactical tie-breaking | Two-card market lookahead with extra value for champions, topdeck effects, stun lines, and on-faction synergy |


## Card Art Validation

Use `res://tests/TestCardArt.gd` to validate that key card art paths resolve and raw image files can be loaded headlessly.

```bash
"/c/Users/devinsGamingPC/Downloads/Godot_v4.5.1-stable_win64.exe/Godot_v4.5.1-stable_win64_console.exe" --headless --path . --scene res://tests/TestCardArtRunner.tscn
```

Optional CLI run (headless):

```bash
"/c/Users/devinsGamingPC/Downloads/Godot_v4.5.1-stable_win64.exe/Godot_v4.5.1-stable_win64_console.exe" --headless --path . --scene res://tests/NoUISimRunner.tscn
```
