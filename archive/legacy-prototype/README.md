# Legacy prototype

The original prototype engine (`src/engine.py`, `src/ai.py`, `src/ui.py`,
`src/simple-start/basic.py`) and its benchmark (`benchmark.py`), moved here
2026-09-12. Superseded by the real implementation at the repo root
(`hero_engine.py`, `hero_ai.py`, `hero_realms_gui.py`).

`benchmark.py` still runs from inside this directory (it imports `src.*`
relatively), as do the legacy tests (`tests/`, run from here). Nothing
outside this folder references any of it.
