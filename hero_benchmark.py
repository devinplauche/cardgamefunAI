"""Benchmark Hero Realms card win rates and AI strategy performance."""

import random
import statistics
from collections import defaultdict
from hero_engine import HRGame, HRPlayer, HRCard, load_hero_cards
from hero_ai import AggressiveAI, EconomicAI, ChampionAI, BalancedAI


def simulate_game(ai1, ai2, market_cards: list[HRCard], seed: int | None = None) -> dict:
    if seed is not None:
        random.seed(seed)

    p1 = HRPlayer("P1")
    p2 = HRPlayer("P2")
    game = HRGame(p1, p2, [HRCard(**c.__dict__) for c in market_cards])

    cards_played_by_winner: list[str] = []
    cards_bought_by_winner: list[str] = []

    turn_winner = 0
    result_winner = None

    og_play = ai1.play
    og_buy = ai1.buy

    def tracked_play(player, opponent, market):
        og_play(player, opponent, market)

    def tracked_buy(player, opponent, market):
        og_buy(player, opponent, market)

    ai1.play = tracked_play
    ai1.buy = tracked_buy

    og_play2 = ai2.play
    og_buy2 = ai2.buy

    def tracked_play2(player, opponent, market):
        og_play2(player, opponent, market)

    def tracked_buy2(player, opponent, market):
        og_buy2(player, opponent, market)

    ai2.play = tracked_play2
    ai2.buy = tracked_buy2

    winner, turns, log = game.run_game(
        ai_buy=lambda p, o, m: (ai1.buy if p is p1 else ai2.buy)(p, o, m),
        ai_play=lambda p, o, m: (ai1.play if p is p1 else ai2.play)(p, o, m),
        ai_attack=lambda p, o, g: (ai1.attack if p is p1 else ai2.attack)(p, o, g)
    )

    ai1.play = og_play
    ai1.buy = og_buy
    ai2.play = og_play2
    ai2.buy = og_buy2

    return {
        'winner': winner,
        'turns': turns,
        'p1_strat': ai1.name,
        'p2_strat': ai2.name,
        'p1_hp': p1.hp,
        'p2_hp': p2.hp,
        'p1_board': [(bc.card.id, bc.card.name) for bc in p1.board],
        'p2_board': [(bc.card.id, bc.card.name) for bc in p2.board],
        'p1_discard_ids': [c.id for c in p1.discard],
        'p2_discard_ids': [c.id for c in p2.discard],
    }


def run_benchmark(ai1, ai2, market_cards, num_games=200):
    results = []
    card_wins: dict[str, int] = defaultdict(int)
    card_plays: dict[str, int] = defaultdict(int)
    card_turns: dict[str, list[int]] = defaultdict(list)
    card_bought_wins: dict[str, int] = defaultdict(int)
    card_bought_total: dict[str, int] = defaultdict(int)

    for g in range(num_games):
        seed = 42 + g
        r = simulate_game(ai1, ai2, market_cards, seed=seed)

        if g % 2 == 1:
            r = simulate_game(ai2, ai1, market_cards, seed=seed + 1000)

        results.append(r)

        winner_deck_p1 = [c.id for c in r.get('p1_discard', [])]
        winner_deck_p2 = [c.id for c in r.get('p2_discard', [])]
        p1_won = r['winner'] == 'P1'
        winner_ids = set(
            cid for cid in (r['p1_discard_ids'] if p1_won else r['p2_discard_ids'])
            if cid not in ('gold', 'shortsword', 'dagger', 'ruby')
        )

        for cid in winner_ids:
            card_wins[cid] += 1

        all_ids = set(
            cid for cid in r['p1_discard_ids'] + r['p2_discard_ids']
            if cid not in ('gold', 'shortsword', 'dagger', 'ruby')
        )
        for cid in all_ids:
            card_plays[cid] += 1

    strat_a_wins = sum(1 for r in results
                       if (r['winner'] == 'P1' and r['p1_strat'] == ai1.name) or
                       (r['winner'] == 'P2' and r['p2_strat'] == ai1.name))
    strat_b_wins = num_games - strat_a_wins
    draws = 0

    win_turns = [r['turns'] for r in results]

    card_stats = {}
    all_market_ids = set(c.id for c in market_cards)
    for c in market_cards:
        cid = c.id
        played = card_plays.get(cid, 0)
        wins = card_wins.get(cid, 0)
        win_rate = (wins / played * 100) if played > 0 else 0.0
        card_stats[cid] = {
            'name': c.name,
            'cost': c.cost,
            'type': c.card_type,
            'faction': c.faction,
            'played': played,
            'wins': wins,
            'win_rate': round(win_rate, 1),
        }

    return {
        'label': f"{ai1.name} vs {ai2.name}",
        'num_games': num_games,
        'strat_a': ai1.name,
        'strat_b': ai2.name,
        'strat_a_wins': strat_a_wins,
        'strat_b_wins': strat_b_wins,
        'draws': draws,
        'avg_win_turns': round(statistics.mean(win_turns), 1),
        'median_win_turns': round(statistics.median(win_turns), 1),
        'min_turns': min(win_turns),
        'max_turns': max(win_turns),
        'card_stats': card_stats,
    }


def print_results(stats: dict):
    a = stats['strat_a']
    b = stats['strat_b']
    a_w = stats['strat_a_wins']
    b_w = stats['strat_b_wins']
    total = a_w + b_w

    print(f"\n{'='*70}")
    print(f"  {stats['label']}")
    print(f"{'='*70}")
    print(f"  Games: {stats['num_games']}")
    print(f"  {a}: {a_w} wins ({round(a_w/total*100,1) if total else 0}%)")
    print(f"  {b}: {b_w} wins ({round(b_w/total*100,1) if total else 0}%)")
    print(f"  Win turns: avg={stats['avg_win_turns']}, median={stats['median_win_turns']}, "
          f"min={stats['min_turns']}, max={stats['max_turns']}")
    print(f"\n  Cards ranked by win rate (min 5 plays):")
    print(f"  {'Name':<28} {'Cost':<6} {'Type':<12} {'Win%':<8} {'Plays':<8}")
    print(f"  {'-'*62}")
    sorted_cards = sorted(stats['card_stats'].values(), key=lambda x: -x['win_rate'])
    for cs in sorted_cards:
        if cs['played'] >= 5:
            t = cs['type'][:10]
            print(f"  {cs['name']:<28.28s} {cs['cost']:<6} {t:<12} {cs['win_rate']:<8} {cs['played']:<8}")
    print()


if __name__ == '__main__':
    random.seed(42)
    market_cards = load_hero_cards("data/hero_realms_cards.json")
    print(f"Loaded {len(market_cards)} market cards")

    profiles = [AggressiveAI, EconomicAI, ChampionAI, BalancedAI]

    for i, ai1 in enumerate(profiles):
        for ai2 in profiles[i:]:
            s = run_benchmark(ai1(), ai2(), market_cards, num_games=100)
            print_results(s)
