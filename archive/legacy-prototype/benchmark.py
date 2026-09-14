"""Benchmark: evaluate card win rates and AI strategy performance via simulation."""

import random
import statistics
from collections import defaultdict
from src.engine import Card, Deck, Player, Game, load_cards_from_file
from src.ai import AggressiveAI, DefensiveAI, BalancedAI, RandomAI


ALL_CARDS: list[Card] = []


def build_deck(deck_size: int = 20) -> list[Card]:
    return random.sample(ALL_CARDS, min(deck_size, len(ALL_CARDS)))


def simulate_game(
    p1_strategy_cls,
    p2_strategy_cls,
    deck_size: int = 20,
    max_rounds: int = 100,
) -> dict:
    cards1 = build_deck(deck_size)
    cards2 = build_deck(deck_size)

    p1 = Player("P1", deck=Deck(cards1))
    p2 = Player("P2", deck=Deck(cards2))

    p1.draw(4)
    p2.draw(4)

    game = Game([p1, p2])

    card_played_by: dict[str, list[str]] = {}
    turn_played: dict[str, list[int]] = {}

    winner = None
    total_turns = 0

    game.turn_manager.start_turn()
    total_turns = 1

    for _ in range(max_rounds):
        active = game.turn_manager.active_player
        target = p2 if active is p1 else p1
        strat = p1_strategy_cls if active is p1 else p2_strategy_cls

        try:
            card = strat.choose_card(active, target)
            if card:
                cid = card.id
                if cid not in card_played_by:
                    card_played_by[cid] = []
                    turn_played[cid] = []
                card_played_by[cid].append(active.name)
                turn_played[cid].append(total_turns)
                active.play_card(card, target=target)
        except Exception:
            pass

        game.turn_manager.phase = 'resolve'
        game.resolve_stack()

        if p1.hp <= 0:
            winner = "P2"
            break
        if p2.hp <= 0:
            winner = "P1"
            break

        game.turn_manager.advance_phase()
        total_turns += 1

    return {
        'winner': winner,
        'turns': total_turns,
        'card_played_by': card_played_by,
        'turn_played': turn_played,
        'p1_strategy': p1_strategy_cls.__name__,
        'p2_strategy': p2_strategy_cls.__name__,
    }


def run_benchmark(
    label: str,
    strat_a,
    strat_b,
    num_games: int = 500,
    deck_size: int = 20,
) -> dict:
    results = []
    card_wins: dict[str, int] = defaultdict(int)
    card_plays: dict[str, int] = defaultdict(int)
    card_turns: dict[str, list[int]] = defaultdict(list)

    for g in range(num_games):
        if g % 2 == 0:
            r = simulate_game(strat_a, strat_b, deck_size)
        else:
            r = simulate_game(strat_b, strat_a, deck_size)
        results.append(r)

        for cid, player_names in r['card_played_by'].items():
            turns_list = r['turn_played'].get(cid, [])
            for i, pname in enumerate(player_names):
                card_plays[cid] += 1
                is_winner = (
                    (r['winner'] == 'P1' and pname == 'P1') or
                    (r['winner'] == 'P2' and pname == 'P2')
                )
                if is_winner:
                    card_wins[cid] += 1
                if i < len(turns_list) and turns_list[i] > 0:
                    card_turns[cid].append(turns_list[i])

    strat_a_wins = 0
    strat_b_wins = 0
    for r in results:
        if r['winner'] == 'P1':
            if r['p1_strategy'] == strat_a.__name__:
                strat_a_wins += 1
            else:
                strat_b_wins += 1
        elif r['winner'] == 'P2':
            if r['p2_strategy'] == strat_a.__name__:
                strat_a_wins += 1
            else:
                strat_b_wins += 1

    win_turns = [r['turns'] for r in results if r['winner'] is not None]

    card_stats = {}
    for c in ALL_CARDS:
        cid = c.id
        played = card_plays.get(cid, 0)
        wins = card_wins.get(cid, 0)
        win_rate = (wins / played * 100) if played > 0 else 0.0
        turns = card_turns.get(cid, [])
        avg_turn = statistics.mean(turns) if turns else 0.0
        card_stats[cid] = {
            'name': c.name,
            'played': played,
            'wins': wins,
            'win_rate': round(win_rate, 1),
            'avg_turn': round(avg_turn, 1),
        }

    return {
        'label': label,
        'num_games': num_games,
        'strat_a': strat_a.__name__,
        'strat_b': strat_b.__name__,
        'strat_a_wins': strat_a_wins,
        'strat_b_wins': strat_b_wins,
        'draws': num_games - strat_a_wins - strat_b_wins,
        'avg_win_turns': round(statistics.mean(win_turns), 1) if win_turns else 0,
        'median_win_turns': round(statistics.median(win_turns), 1) if win_turns else 0,
        'min_turns': min(win_turns) if win_turns else 0,
        'max_turns': max(win_turns) if win_turns else 0,
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
    print(f"  Games: {stats['num_games']} (alternating first-player)")
    print(f"  {a}: {a_w} wins ({round(a_w/total*100,1) if total else 0}%)")
    print(f"  {b}: {b_w} wins ({round(b_w/total*100,1) if total else 0}%)")
    print(f"  Draws: {stats['draws']}")
    print(f"  Win turns: avg={stats['avg_win_turns']}, median={stats['median_win_turns']}, "
          f"min={stats['min_turns']}, max={stats['max_turns']}")
    print(f"\n  Cards ranked by played win rate (min 10 plays):")
    print(f"  {'Name':<22} {'Win%':<8} {'Plays':<8} {'AvgTurnPlayed':<15}")
    print(f"  {'-'*53}")
    sorted_cards = sorted(stats['card_stats'].values(), key=lambda x: -x['win_rate'])
    for cs in sorted_cards:
        if cs['played'] >= 10:
            print(f"  {cs['name']:<22.22s} {cs['win_rate']:<8} {cs['played']:<8} {cs['avg_turn']:<15}")
    print()


if __name__ == '__main__':
    random.seed(42)
    ALL_CARDS = load_cards_from_file('data/cards.json')
    print(f"Loaded {len(ALL_CARDS)} cards from data/cards.json")

    strategies = [
        ("RandomAI", RandomAI),
        ("AggressiveAI", AggressiveAI),
        ("BalancedAI", BalancedAI),
        ("DefensiveAI", DefensiveAI),
    ]

    results_by_card: dict[str, dict] = {}

    for name1, cls1 in strategies:
        for name2, cls2 in strategies:
            if strategies.index((name1, cls1)) > strategies.index((name2, cls2)):
                continue
            label = f"{name1} vs {name2}"
            s = run_benchmark(label, cls1, cls2, num_games=400, deck_size=20)
            print_results(s)

            for cid, cs in s['card_stats'].items():
                if cid not in results_by_card:
                    results_by_card[cid] = {
                        'name': cs['name'],
                        'total_plays': 0,
                        'total_wins': 0,
                        'all_turns': [],
                    }
                results_by_card[cid]['total_plays'] += cs['played']
                results_by_card[cid]['total_wins'] += cs['wins']

    print(f"\n{'='*70}")
    print(f"  FINAL CARD RANKINGS (when played, all {len(strategies)*(len(strategies)+1)//2} matchups)")
    print(f"{'='*70}")
    print(f"  {'Rank':<6} {'Name':<22} {'Win%':<8} {'TimesPlayed':<12}")
    print(f"  {'-'*48}")
    ranked = sorted(results_by_card.values(), key=lambda x: -(x['total_wins']/max(1,x['total_plays'])*100))
    for i, rc in enumerate(ranked, 1):
        played = rc['total_plays']
        wins = rc['total_wins']
        wr = round(wins / played * 100, 1) if played > 0 else 0
        print(f"  {i:<6} {rc['name']:<22.22s} {wr:<8} {played:<12}")
