# Turn-Based Card Game Implementation Plan

## Overview
- Goal: Build a turn-based card game with a GUI. Start with a quick Python prototype to validate rules and flow, then optionally port to Unity/C# for visuals and cross-platform builds.

## Technology Recommendations
- Fast prototype: **Python** with `tkinter` (desktop, minimal dependencies) or `pygame` (better rendering).
- Polished visuals: **Unity + C#** (recommended if you want animations, mobile/desktop builds, or networking later).
- Web option: **React + Flask/Node** for easy sharing and browser play.

My suggested path: begin with a Python prototype (validate rules, AI, UI flow), then port to Unity if you want richer presentation.

## High-level Game Concept (example)
- Players: 2 (player vs AI or hot-seat).
- Turn phases: Draw → Main (play cards) → Resolve → End.
- Card types: Attack, Defense, Resource, Utility.
- Win condition: Opponent HP ≤ 0.

## Architecture
- `engine/` - core logic: `Game`, `Player`, `Deck`, `Card`, `TurnManager`, `Effects`.
- `ui/` - GUI code: window, board, hand widgets, dialogs.
- `ai/` - simple heuristics for prototype AI.
- `data/` - card definitions (JSON/YAML).
- `assets/` - images, icons, fonts.
- `tests/` - unit tests for rules and edge cases.

## Data Models (concise)
- Card: `{ id, name, cost, type, text, effects }`
- Player: `{ id, name, hp, deck, hand, discard, resources }`
- GameState: `{ players, active_player, phase, turn_number, stack }`
- Effect: modular effect objects or functions (damage, draw, buff).

## Turn Flow
1. StartTurn: replenish resources, draw.
2. Main: player plays cards (cost checks) and activates effects.
3. Resolve: resolve stack/effects.
4. EndTurn: cleanup, check win.

## GUI (MVP)
- Main window with two player areas (top/bottom), center play area.
- Hand strip (clickable cards), play area, and a small log.
- Buttons: `End Turn`, `Shuffle`, `Concede`.
- Modal dialogs for `Card Details` and `Game Over`.

## Milestones & Rough Estimates
- Tech choice & scaffold: 1–2 hours
- Define rules & data model: 1–3 hours
- Engine core (draw/play/turn): 4–8 hours
- GUI prototype (Tkinter): 4–8 hours
- AI + polish: 4–12 hours
- Optional multiplayer/Unity port: additional days

## Next Actions (numbered steps)
1. Scaffold project structure and TDD test harness (`tests/`, `src/engine.py`).
2. Implement deck, card, and player draw logic; unit tests for deck/draw.
3. Implement `TurnManager` and turn progression tests (start, main, end phases).
4. Implement basic card play mechanics and tests (cost checks, effects resolution).
5. Implement simple AI with tests (basic heuristics to play attack cards).
6. Create Tkinter GUI shell and integration tests that launch the GUI.
7. Integrate engine with GUI; add interactive hand and play area.
8. Polish UI, add assets, animations, settings, and save/load.
9. Optional: port to Unity/C# or add multiplayer.

### Quick choices for you
- Recommended start: Option A — Python + `tkinter` to validate rules quickly.
- If you want visuals and cross-platform/mobile later: plan a Unity port after the prototype.

If you confirm, I'll proceed following the numbered steps using TDD: implement tests, write code to satisfy them, and add integration tests that launch the GUI so you can visually confirm progress.
