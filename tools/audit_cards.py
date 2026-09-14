"""Audit every card's printed text against its parsed `effects` dict.

Written after repeatedly finding rules bugs one at a time (ally triggers only
firing off champions, allies not being retroactive, sacrifice effects treated
as mandatory). Each of those was invisible because nothing ever compared what
a card *says* to what the engine *does*.

This parses the printed text for the standard Hero Realms keyword templates
and reports any card where the text and the effects dict disagree. It is a
lint, not a test: some findings are template gaps rather than real bugs, so
it prints for review rather than asserting.

Usage:  python tools/audit_cards.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CARDS_JSON = REPO / "data" / "hero_realms_cards.json"

NUM = r"(\d+)"
PATTERNS = {
    "combat": re.compile(r"\{Gain " + NUM + r" combat\}", re.I),
    "gold": re.compile(r"\{Gain " + NUM + r" gold\}", re.I),
    "health": re.compile(r"\{Gain " + NUM + r" health\}", re.I),
}
DRAW_ONE = re.compile(r"draw a card", re.I)
DRAW_N = re.compile(r"draw (two|three|\d+) cards", re.I)
WORD_NUM = {"two": 2, "three": 3, "four": 4}


def split_sections(text: str) -> dict:
    """Split card text into base / ally / sacrifice sections.

    Cards use <hr> to separate the base effect from {Faction Ally}: and
    {Sacrifice}: clauses, so a number in the ally section must map to an
    ally_* key rather than the base one.
    """
    parts = [p.strip() for p in re.split(r"<hr>", text)]
    out = {"base": [], "ally": [], "sacrifice": []}
    for part in parts:
        if re.match(r"\{(Imperial|Necros|Wild|Guild) Ally\}", part, re.I):
            out["ally"].append(part)
        elif re.match(r"\{Sacrifice\}", part, re.I):
            out["sacrifice"].append(part)
        else:
            out["base"].append(part)
    return {k: "\n".join(v) for k, v in out.items()}


def expected_from_text(text: str) -> dict:
    """Best-effort expected effects, keyed like the engine's effects dict."""
    sections = split_sections(text)
    exp: dict[str, int] = {}

    for section, prefix in (("base", ""), ("ally", "ally_"), ("sacrifice", "sacrifice_")):
        body = sections[section]
        if not body:
            continue
        for key, pattern in PATTERNS.items():
            found = [int(m) for m in pattern.findall(body)]
            if found:
                exp[prefix + key] = sum(found)
        if DRAW_ONE.search(body):
            exp[prefix + "draw"] = exp.get(prefix + "draw", 0) + 1
        for m in DRAW_N.findall(body):
            n = WORD_NUM.get(m.lower(), None)
            n = int(m) if n is None and m.isdigit() else n
            if n:
                exp[prefix + "draw"] = exp.get(prefix + "draw", 0) + n
    return exp


def audit():
    data = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    findings = []

    for card in data:
        text = card.get("text") or ""
        eff = card.get("effects", {})
        name = card["name"]
        if not text:
            findings.append((name, "no printed text to audit against", "", ""))
            continue

        expected = expected_from_text(text)
        for key, want in expected.items():
            # sacrifice_combat is the engine's key for "{Sacrifice}: gain N combat"
            got = eff.get(key)
            if got is None and key == "sacrifice_combat":
                got = eff.get("sacrifice_combat")
            if got is None:
                findings.append((name, f"text implies {key}={want}", "missing from effects", text))
            elif got != want:
                findings.append((name, f"text implies {key}={want}", f"effects has {got}", text))

        # Ally section present but no ally_faction recorded (or vice versa).
        has_ally_text = bool(re.search(r"\{(Imperial|Necros|Wild|Guild) Ally\}", text, re.I))
        if has_ally_text != ("ally_faction" in eff):
            findings.append((name, f"ally text={has_ally_text}", f"ally_faction in effects={'ally_faction' in eff}", text))

        # Guard keyword vs guard stat.
        has_guard_text = bool(re.search(r"\bguard\b", text, re.I)) and card.get("type") == "champion"
        if has_guard_text and not card.get("guard"):
            findings.append((name, "text mentions Guard", f"guard={card.get('guard')}", text))

    print(f"audited {len(data)} cards, {len(findings)} discrepancies\n")
    for name, want, got, text in findings:
        print(f"  {name:<26} {want:<34} {got}")
        if text:
            print(f"  {'':<26} text: {text.replace(chr(10), ' | ')[:110]}")
    return findings


if __name__ == "__main__":
    audit()
