"""Parse hero-realms-base-cards.txt into structured JSON."""
import csv
import json
import re

INPUT = r"C:\Users\devinsGamingPC\Coding\card-game\cards\hero-realms-base-cards.txt"
OUTPUT = "data/hero_realms_cards.json"

def parse_effects(text: str) -> dict:
    """Extract structured effects from card text."""
    effects = {}

    gold_m = re.findall(r'\{Gain (\d+) gold\}', text)
    if gold_m:
        effects['gold'] = sum(int(g) for g in gold_m)

    combat_m = re.findall(r'\{Gain (\d+) combat\}', text)
    if combat_m:
        effects['combat'] = sum(int(c) for c in combat_m)

    health_m = re.findall(r'\{Gain (\d+) health\}', text)
    if health_m:
        effects['health'] = sum(int(h) for h in health_m)

    draw_m = re.findall(r'Draw a card', text)
    if draw_m:
        effects['draw'] = len(draw_m)

    discard_m = re.findall(r'discard a card', text)
    if discard_m:
        effects['discard'] = len(discard_m)

    sacrifice_m = re.findall(r'\{Sacrifice\}', text)
    if sacrifice_m:
        effects['sacrifice_combat'] = 5
        sacrifice_match = re.search(r'\{Sacrifice\}:\s*\{Gain (\d+) combat\}', text)
        if sacrifice_match:
            effects['sacrifice_combat'] = int(sacrifice_match.group(1))

    if 'Draw two cards' in text:
        effects['draw'] = 2
    if 'draw up to two cards' in text:
        effects['draw'] = 2
        effects['discard_drawn'] = True

    if 'Stun target champion' in text:
        effects['stun'] = True

    if 'Prepare a champion' in text:
        effects['prepare'] = True

    if 'Put the next card you acquire this turn into your hand' in text:
        effects['to_hand'] = True

    if 'Put the next' in text and 'on top of your deck' in text:
        effects['top_of_deck'] = True

    if 'You may put a card from your discard pile on top of your deck' in text:
        effects['recycle'] = True

    if 'Take a champion from your discard pile and put it on top of your deck' in text:
        effects['reanimate'] = True

    ally_match = re.search(r'\{(\w+) Ally\}', text)
    if ally_match:
        effects['ally_faction'] = ally_match.group(1)
        ally_combat = re.search(r'\{(\w+) Ally\}:\s*\{Gain (\d+) combat\}', text)
        if ally_combat:
            effects['ally_combat'] = int(ally_combat.group(2))
        ally_health = re.search(r'\{(\w+) Ally\}:\s*\{Gain (\d+) health\}', text)
        if ally_health:
            effects['ally_health'] = int(ally_health.group(2))
        ally_gold = re.search(r'\{(\w+) Ally\}:\s*\{Gain (\d+) gold\}', text)
        if ally_gold:
            effects['ally_gold'] = int(ally_gold.group(2))
        # Check if Draw a card is part of ally section (after {X Ally}:)
        for section in text.split('<hr>'):
            if '{' + effects['ally_faction'] + ' Ally}:' in section and 'Draw a card' in section:
                effects['ally_draw'] = 1

    return effects


def main():
    cards = []
    with open(INPUT, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 6:
                continue
            col = [c.strip() for c in row]
            name = col[2]
            text = col[3]
            type_str = col[4]
            faction = col[5] if len(col) > 5 else ""
            cost_str = col[6] if len(col) > 6 else "0"
            stats_str = col[7] if len(col) > 7 else ""
            location = col[8] if len(col) > 8 else ""

            cost = int(cost_str) if cost_str.isdigit() else 0

            is_champion = "champion" in type_str.lower()
            subtypes = []
            if "◆" in type_str:
                parts = [p.strip() for p in type_str.split("◆")]
                card_type = parts[0].strip().lower()
                subtypes = parts[1:]
            else:
                card_type = type_str.strip().lower()

            guard = 0
            health = 0
            if is_champion:
                if "guard" in stats_str.lower():
                    guard = 1
                health_str = stats_str.lower().replace("guard", "").strip()
                health = int(health_str) if health_str.isdigit() else 0

            effects = parse_effects(text)

            card = {
                "id": f"hr_{len(cards)+1:03d}",
                "name": name,
                "cost": cost,
                "faction": faction,
                "type": card_type,
                "subtypes": subtypes,
                "guard": guard,
                "health": health,
                "text": text,
                "effects": effects,
                "location": location,
            }
            cards.append(card)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2)

    print(f"Parsed {len(cards)} card(s) to {OUTPUT}")


if __name__ == "__main__":
    main()
