"""Feasibility probe: can OpenSpiel compute exploitability for this project?

WHY THIS EXISTS

Every number in this repo is a win rate against four fixed heuristic profiles.
That instrument has three defects nothing in the repo can fix: ~10pp seed-block
noise, saturation (16x more search compute buys nothing), and no answer to "is
58% good?" because the opponent pool is weak and fixed. OpenSpiel offers one
thing the repo genuinely cannot compute - exploitability against an exact best
response, an absolute measure that does not depend on the opponent pool.

VERDICT: NOT COMPUTABLE AT A USEFUL SCALE. Do not build the game class.

Two independent walls, measured below and reproducible with this file:

  1. The full game is ~10^177 histories against a best-response budget of
     ~10^6-10^7. That is ~170 orders of magnitude, so no amount of engineering
     closes it.
  2. A *reduced* variant does not rescue it either. OpenSpiel's tabular best
     response memoises on `state.history_str()` - it has no transposition
     table - and the free-order Main phase this project deliberately restored
     generates k! histories for every k commuting actions. Cost scales at
     ~115x PER TURN, so the smallest variant in which deckbuilding exists at
     all (a bought card survives a reshuffle and gets played) is ~10^12
     histories, about a decade of best response.

The second wall is the interesting one, and it is worth stating precisely
because it is easy to mis-attribute: the blocker is NOT the 80-card market, the
50 HP, or the card pool. Market size is nearly free (4 market cards cost 4.6x
over 1). It is game *length* interacting with free action ordering.

WHAT TO DO INSTEAD

Exploitability's appeal was that it does not depend on the opponent pool. A
*learned* best response keeps that property and needs no reimplementation:
freeze the shipped policy and train an exploiter against it in the real engine
(the repo already has the pieces - `hero_rl_train_v*.py`, `hero_rl_vs_mcts.py`).
Its win rate is a lower bound on exploitability. A lower bound from the real
game is worth more than an exact number from a variant with one market card.

REPRODUCE

    pip install open_spiel                # 2.0.1, cp314 win_amd64 wheel exists
    python hero_openspiel_probe.py all

Nothing here is imported by the shipped bot. OpenSpiel is needed only for the
`reference` subcommand; every sizing number runs without it.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import Counter
from math import comb

# Best-response throughput, measured by the `reference` subcommand on this
# machine: ~30k histories/s for a C++ game, ~8k/s for a Python game class on a
# trivial game. A Python game doing real card logic per transition lands below
# that, so 5k/s is the optimistic figure used for every time estimate here.
BR_RATE = 5_000


def fmt_time(histories: float) -> str:
    s = histories / BR_RATE
    if s < 90:            return f"{s:,.0f}s"
    if s < 5400:          return f"{s / 60:,.1f}m"
    if s < 86400:         return f"{s / 3600:,.1f}h"
    if s < 86400 * 730:   return f"{s / 86400:,.0f}d"
    return f"{s / (86400 * 365):.3g}yr"


# ===================================================================== stage 0
# How big is the real game? Measured against the real engine, not assumed.

def stage0_full_game(games: int = 60, policy: str = "greedy") -> None:
    """Drive the shipped engine and count what a game tree would contain."""
    import random
    from web.session import GameSession, FREEFORM_TURN
    from web.bot import apply_action

    rng = random.Random(12345)
    rows = []
    for i in range(games):
        s = GameSession(seed=1000 + i, algorithm="heuristic", budget_ms=1)
        s.record_history = False
        log_branch = log_chance = 0.0
        branches, chance = [], 0
        while s.winner is None and s.turn_number <= 200:
            acts = s.legal_actions()
            if not acts:
                break
            if len(acts) > 1:
                log_branch += math.log10(len(acts))
            branches.append(len(acts))
            a = (max(acts, key=lambda x: x.get("priority", 0)) if policy == "greedy"
                 else rng.choice(acts))
            ending = a["type"] == "advance_phase"
            cur = s._current()
            pool = len(cur.deck) + len(cur.discard) + len(cur.hand)
            try:
                apply_action(s, a)
            except ValueError:
                break
            if ending:
                chance += 1
                if pool >= 5:
                    log_chance += math.log10(comb(pool, 5))
        rows.append(dict(turns=s.turn_number, branches=branches,
                         chance=chance, lb=log_branch, lc=log_chance))

    allb = [b for r in rows for b in r["branches"]]
    dec = statistics.mean(len(r["branches"]) for r in rows)
    lb = statistics.mean(r["lb"] for r in rows)
    lc = statistics.mean(r["lc"] for r in rows)

    print(f"--- stage 0: full Hero Realms (FREEFORM_TURN={FREEFORM_TURN}, "
          f"policy={policy}, {games} games) ---")
    print(f"turns / game            {statistics.mean(r['turns'] for r in rows):>8.1f}")
    print(f"decisions / game        {dec:>8.1f}")
    print(f"branching factor        {statistics.mean(allb):>8.2f}   "
          f"median {statistics.median(allb):.0f}  max {max(allb)}")
    print(f"shuffles / game         {statistics.mean(r['chance'] for r in rows):>8.1f}")
    print()
    print(f"log10 action histories along one line   {lb:>8.1f}")
    print(f"log10 chance outcomes  along one line   {lc:>8.1f}")
    print(f"log10 TOTAL histories                   {lb + lc:>8.1f}")
    print(f"mean-field b^d = {statistics.mean(allb):.2f}^{dec:.0f} "
          f"= 10^{dec * math.log10(statistics.mean(allb)):.1f}")


def stage0_infostates(games: int = 400, policy: str = "random") -> None:
    """Do information states ever repeat? (If they do not, the space is not
    enumerable and no further argument is needed.)"""
    import random
    from web.session import GameSession
    from web.bot import apply_action

    def key(s) -> tuple:
        me, opp = s._current(), s._opponent()
        return (
            s.active_player, s.phase, s.turn_number, me.hp, opp.hp,
            me.gold, me.combat,
            tuple(sorted(c.id for c in me.hand)),
            # deck ORDER is hidden even from its owner, so composition only
            tuple(sorted(Counter(c.id for c in me.deck).items())),
            tuple(sorted(Counter(c.id for c in me.discard).items())),
            tuple(sorted((b.card.id, b.current_health, b.exhausted) for b in me.board)),
            tuple(sorted(c.id for c in me.played_this_turn)),
            len(opp.hand), len(opp.deck),
            tuple(sorted(Counter(c.id for c in opp.discard).items())),
            tuple(sorted((b.card.id, b.current_health, b.exhausted) for b in opp.board)),
            tuple(c.id if c else None for c in s.market.row),
            s.market.fire_gems_remaining,
        )

    rng = random.Random(999)
    seen, visits, marks = set(), 0, []
    for g in range(games):
        s = GameSession(seed=200_000 + g, algorithm="heuristic", budget_ms=1)
        s.record_history = False
        while s.winner is None and s.turn_number <= 60:
            acts = s.legal_actions()
            if not acts:
                break
            seen.add(key(s))
            visits += 1
            a = (max(acts, key=lambda x: x.get("priority", 0)) if policy == "greedy"
                 else rng.choice(acts))
            try:
                apply_action(s, a)
            except ValueError:
                break
        if (g + 1) in (25, 100, 400):
            marks.append((g + 1, visits, len(seen)))

    print(f"--- stage 0: information-state saturation (policy={policy}) ---")
    print(f"{'games':>7}{'visits':>10}{'distinct':>10}{'ratio':>8}")
    for g, v, u in marks + [(games, visits, len(seen))]:
        print(f"{g:>7}{v:>10,}{u:>10,}{u / v:>8.4f}")
    print("A ratio pinned at 1.0000 means not one information state was ever")
    print("revisited. The space shows no sign of saturating.")

    hp, market = 50 * 50, comb(55, 5)
    deck = comb(56 + 12 - 1, 12)   # ~12 cards acquired per game from 56 types
    total = hp * market * deck * deck
    print(f"\ncombinatorial lower bound on three provably independent components:")
    print(f"  HP pair                10^{math.log10(hp):.1f}")
    print(f"  market row (5 of 55)   10^{math.log10(market):.1f}")
    print(f"  acquired deck, x2      10^{2 * math.log10(deck):.1f}")
    print(f"  product                10^{math.log10(total):.1f}"
          f"   (hand/deck/discard partition, board, gold, combat all excluded)")


def stage0_reference() -> None:
    """Confirm OpenSpiel works and measure the best-response budget."""
    import time
    import pyspiel
    from open_spiel.python import policy as policy_lib
    from open_spiel.python.algorithms import exploitability

    def histories(state) -> int:
        if state.is_terminal():
            return 1
        acts = ([o for o, _ in state.chance_outcomes()] if state.is_chance_node()
                else state.legal_actions())
        return 1 + sum(histories(state.child(a)) for a in acts)

    print("--- stage 0: OpenSpiel reference (does it work, and how fast) ---")
    print(f"pyspiel {pyspiel.__file__}")
    print(f"{'game':<20}{'impl':<8}{'histories':>12}{'secs':>9}{'hist/s':>12}"
          f"{'nash_conv':>12}")
    for name in ("kuhn_poker", "python_kuhn_poker", "leduc_poker", "liars_dice"):
        g = pyspiel.load_game(name)
        h = histories(g.new_initial_state())
        t = time.time()
        nc = exploitability.nash_conv(g, policy_lib.UniformRandomPolicy(g))
        dt = time.time() - t
        impl = "PYTHON" if name.startswith("python_") else "C++"
        print(f"{name:<20}{impl:<8}{h:>12,}{dt:>9.3f}{h / max(dt, 1e-9):>12,.0f}"
              f"{nc:>12.4f}")
    print("\nBest response is O(#histories): `BestResponsePolicy.value` memoises")
    print("on `state.history_str()`, so identical states reached by different")
    print("action orders are paid for separately. That is the whole problem.")


# ===================================================================== stage 1
# HR-mini: the smallest variant that keeps the mechanics this project cares
# about - free-order Main phase, ally triggers, champions with guard, a market.
#
# Decks are modelled as MULTISETS with hypergeometric draw probabilities. That
# is distributionally identical to shuffling a list and is what makes chance
# branching countable at all.

#              name          cost gold combat champ_hp guard faction ally sac
_GOLD        = ("Gold",         0,   1,     0,       0, False, "",       0, 0)
_DAGGER      = ("Dagger",       0,   0,     1,       0, False, "",       0, 0)
_RUBY        = ("Ruby",         0,   2,     0,       0, False, "",       0, 0)
_DEATHTOUCH  = ("DeathTouch",   1,   0,     2,       0, False, "Necros", 2, 0)
_DEATHCULT   = ("DeathCultist", 2,   0,     0,       3, True,  "Necros", 0, 0)
_CULTPRIEST  = ("CultPriest",   3,   0,     0,       4, False, "Necros", 4, 0)
_FIREGEM     = ("FireGem",      2,   2,     0,       0, False, "",       0, 3)

CARDS = [_GOLD, _DAGGER, _RUBY, _DEATHTOUCH, _DEATHCULT, _CULTPRIEST, _FIREGEM]
COST, GOLD, COMBAT, CHP, GUARD, FACT, ALLY, SAC = 1, 2, 3, 4, 5, 6, 7, 8
CHAMP_EXPEND = {4: (0, 2), 5: (1, 1)}     # card index -> (gold, combat)
CAT = {"play": 0, "expend": 1, "sac": 2, "buy": 3}


class Cfg:
    def __init__(self, hp=15, hand=3, market=(3, 4, 5, 6), start=(0, 0, 1, 2),
                 turn_cap=8):
        self.hp, self.hand = hp, hand
        self.market, self.start, self.turn_cap = tuple(market), tuple(start), turn_cap


def _ms(d):
    return tuple(sorted((k, v) for k, v in d.items() if v > 0))


def _dd(m):
    return {k: v for k, v in m}


def _hyper(deck_d, n):
    """Distinct n-card draws from a multiset, with probabilities."""
    items = sorted(deck_d.items())
    total = sum(deck_d.values())
    res = []

    def rec(i, left, chosen, ways):
        if left == 0:
            res.append((tuple(chosen), ways))
            return
        if i >= len(items):
            return
        k, cnt = items[i]
        remaining = sum(c for _, c in items[i + 1:])
        for take in range(min(cnt, left) + 1):
            if left - take > remaining:
                continue
            rec(i + 1, left - take, chosen + ([(k, take)] if take else []),
                ways * comb(cnt, take))

    rec(0, n, [], 1)
    denom = comb(total, n)
    out = []
    for drawn, ways in res:
        nd = dict(deck_d)
        for k, v in drawn:
            nd[k] -= v
        out.append((_ms(nd), _ms(dict(drawn)), ways / denom))
    return out


def _draw(deck, discard, n):
    dd = _dd(deck)
    if sum(dd.values()) >= n:
        return [(nd, discard, drawn, p) for nd, drawn, p in _hyper(dd, n)]
    rest = n - sum(dd.values())
    dis = _dd(discard)
    if not sum(dis.values()):
        return [(_ms({}), _ms({}), deck, 1.0)]
    out = []
    for nd, drawn2, p in _hyper(dis, min(rest, sum(dis.values()))):
        merged = _dd(deck)
        for k, v in drawn2:
            merged[k] = merged.get(k, 0) + v
        out.append((nd, _ms({}), _ms(merged), p))
    return out


class Mini:
    """State: (kind, turn, side, hp, ohp, gold, combat, hand, deck, disc,
    played, board, ohand, odeck, odisc, oplayed, oboard[, canon_token])."""

    def __init__(self, cfg: Cfg, canonical: bool = False):
        self.cfg, self.canonical = cfg, canonical

    def new(self):
        d = _ms({i: self.cfg.start.count(i) for i in set(self.cfg.start)})
        s = ("chance", 1, 0, self.cfg.hp, self.cfg.hp, 0, 0,
             _ms({}), d, _ms({}), _ms({}), (),
             _ms({}), d, _ms({}), _ms({}), ())
        return s + ((-1, -1),) if self.canonical else s

    def _core(self, s):
        return s[:-1] if self.canonical else s

    def is_terminal(self, s):
        return s[0] == "term"

    def children(self, s):
        c = self._core(s)
        if c[0] == "chance":
            (_, turn, side, hp, ohp, _g, _c, hand, deck, disc, played, board,
             ohand, odeck, odisc, oplayed, oboard) = c
            out = []
            for nd, ndisc, drawn, _p in _draw(deck, disc, self.cfg.hand):
                nh = _dd(hand)
                for k, v in drawn:
                    nh[k] = nh.get(k, 0) + v
                ns = ("play", turn, side, hp, ohp, 0, 0, _ms(nh), nd, ndisc,
                      played, board, ohand, odeck, odisc, oplayed, oboard)
                out.append(ns + ((-1, -1),) if self.canonical else ns)
            return out
        return [self.apply(s, a) for a in self.legal(s)]

    def legal(self, s):
        (_, _t, _sd, _hp, _ohp, g, cbt, hand, _dk, _ds, played, board,
         _oh, _od, _odc, _op, oboard) = self._core(s)
        acts = [("play", k) for k, _ in hand]
        acts += [("expend", i) for i, (k, _h, ex) in enumerate(board)
                 if not ex and k in CHAMP_EXPEND]
        acts += [("sac", k) for k, _ in played if CARDS[k][SAC]]
        acts += [("buy", k) for k in self.cfg.market if CARDS[k][COST] <= g]
        if cbt > 0:
            guards = [i for i, (k, _h, _e) in enumerate(oboard) if CARDS[k][GUARD]]
            acts += ([("atk_ch", i) for i in guards] if guards else
                     [("atk_face", 0)] + [("atk_ch", i) for i in range(len(oboard))])
        acts.append(("end", 0))
        if not self.canonical:
            return acts
        # Canonical order over COMMUTING actions only. An attack (or end of
        # turn) closes the segment and unlocks the whole cycle again, so
        # buy-then-act and attack-then-buy stay reachable - this is a quotient
        # of the tree, NOT the fixed-phase ratchet. `stage1_canonical` asserts
        # the reachable state set is unchanged.
        last = s[-1]
        return [a for a in acts
                if a[0] not in CAT or (CAT[a[0]], a[1]) >= last]

    def apply(self, s, a):
        (kind, turn, side, hp, ohp, g, cbt, hand, deck, disc, played, board,
         ohand, odeck, odisc, oplayed, oboard) = self._core(s)
        hand_d, played_d = _dd(hand), _dd(played)
        board_l, oboard_l = list(board), list(oboard)
        typ, arg = a

        if typ == "play":
            hand_d[arg] -= 1
            card = CARDS[arg]
            g += card[GOLD]
            cbt += card[COMBAT]
            if card[FACT] and (any(CARDS[j][FACT] == card[FACT] for j, _ in played)
                               or any(CARDS[b][FACT] == card[FACT] for b, _, _ in board_l)):
                cbt += card[ALLY]
            if card[CHP]:
                board_l.append((arg, card[CHP], False))
                # ally is retroactive: a champion arriving triggers faction
                # cards already played this turn
                for j, n in played_d.items():
                    if CARDS[j][FACT] == card[FACT] and CARDS[j][ALLY]:
                        cbt += CARDS[j][ALLY] * n
            else:
                played_d[arg] = played_d.get(arg, 0) + 1
        elif typ == "expend":
            k, chp, _ = board_l[arg]
            dg, dc = CHAMP_EXPEND[k]
            g, cbt = g + dg, cbt + dc
            board_l[arg] = (k, chp, True)
        elif typ == "sac":
            played_d[arg] -= 1
            cbt += CARDS[arg][SAC]
        elif typ == "buy":
            g -= CARDS[arg][COST]
            d = _dd(disc)
            d[arg] = d.get(arg, 0) + 1
            disc = _ms(d)
        elif typ == "atk_face":
            ohp -= cbt
            cbt = 0
        elif typ == "atk_ch":
            k, chp, ex = oboard_l[arg]
            dealt = min(cbt, chp)
            cbt -= dealt
            chp -= dealt
            if chp <= 0:
                oboard_l.pop(arg)
            else:
                oboard_l[arg] = (k, chp, ex)
        elif typ == "end":
            d = _dd(disc)
            for k, n in list(played_d.items()) + list(hand_d.items()):
                if n > 0:
                    d[k] = d.get(k, 0) + n
            disc = _ms(d)
            hand_d, played_d = {}, {}
            board_l = [(k, CARDS[k][CHP], False) for k, _, _ in board_l]
            if ohp <= 0 or turn >= self.cfg.turn_cap:
                ns = ("term", turn, side, hp, ohp, 0, 0, _ms({}), deck, disc,
                      _ms({}), tuple(board_l), ohand, odeck, odisc, oplayed,
                      tuple(oboard_l))
            else:
                ns = ("chance", turn + 1, 1 - side, ohp, hp, 0, 0,
                      ohand, odeck, odisc, oplayed, tuple(oboard_l),
                      _ms(hand_d), deck, disc, _ms(played_d), tuple(board_l))
            return ns + ((-1, -1),) if self.canonical else ns

        kind = "term" if ohp <= 0 else "play"
        ns = (kind, turn, side, hp, ohp, g, cbt, _ms(hand_d), deck, disc,
              _ms(played_d), tuple(board_l), ohand, odeck, odisc, oplayed,
              tuple(oboard_l))
        if not self.canonical:
            return ns
        tok = (CAT[typ], arg) if typ in CAT else (-1, -1)
        return ns + ((-1, -1) if kind == "term" else tok,)


def walk(game: Mini, state_budget=4_000_000):
    """Exact history count by DP over canonical states, plus the reachable
    rules-state set. Histories is what OpenSpiel pays; states is the floor a
    transposition-aware solver could reach."""
    memo, rules = {}, set()

    def rec(s):
        v = memo.get(s)
        if v is not None:
            return v
        if len(memo) > state_budget:
            raise MemoryError(len(memo))
        rules.add(s[:17])
        if game.is_terminal(s):
            memo[s] = 1
            return 1
        memo[s] = None
        n = 1 + sum(rec(k) for k in game.children(s))
        memo[s] = n
        return n

    return rec(game.new()), len(memo), rules


CONFIGS = [
    ("tiny",     Cfg(hp=6,  hand=3, market=(3,),         start=(0, 0, 1),    turn_cap=4)),
    ("tiny+gem", Cfg(hp=8,  hand=3, market=(3, 6),       start=(0, 0, 1),    turn_cap=4)),
    ("small",    Cfg(hp=8,  hand=3, market=(3, 6),       start=(0, 0, 1, 2), turn_cap=6)),
    ("mid",      Cfg(hp=10, hand=3, market=(3, 4, 6),    start=(0, 0, 1, 2), turn_cap=6)),
    ("target",   Cfg(hp=15, hand=3, market=(3, 4, 5, 6), start=(0, 0, 1, 2), turn_cap=8)),
]


def stage1_canonical() -> None:
    print("--- stage 1: reduced variant, free order vs canonical order ---")
    print("'states match' YES proves the canonical quotient removes only")
    print("redundant permutations - it changes no reachable state.\n")
    print(f"{'config':<10}{'free-order hist':>20}{'canon hist':>18}{'saving':>9}"
          f"{'canon BR':>11}{'states match':>14}")
    for label, cfg in CONFIGS:
        try:
            hf, _, sf = walk(Mini(cfg))
            free = f"{hf:,}"
        except MemoryError as e:
            hf, sf, free = None, None, f">{int(str(e)):,} states"
        try:
            hc, _, sc = walk(Mini(cfg, canonical=True))
            canon = f"{hc:,}"
        except MemoryError as e:
            hc, sc, canon = None, None, f">{int(str(e)):,} states"
        print(f"{label:<10}{free:>20}{canon:>18}"
              f"{(f'{hf / hc:,.0f}x' if hf and hc else '-'):>9}"
              f"{(fmt_time(hc) if hc else '-'):>11}"
              f"{('YES' if sf == sc else 'NO') if sf and sc else '?':>14}",
              flush=True)


def stage1_growth() -> None:
    """Which knob actually drives the cost? (Answer: turns. Not the market.)"""
    print("--- stage 1: growth rates, canonical order (the best case) ---")

    def ladder(title, cfgs):
        print(f"\n{title}")
        prev = None
        for tag, cfg in cfgs:
            try:
                h, st, _ = walk(Mini(cfg, canonical=True), state_budget=3_000_000)
            except MemoryError as e:
                print(f"   {tag}  > {int(str(e)):,} states")
                return
            g = f"{h / prev:>7.1f}x" if prev else "      -"
            print(f"   {tag}  histories={h:>18,}  states={st:>10,}"
                  f"  growth={g}  BR={fmt_time(h)}", flush=True)
            prev = h

    ladder("A) turns (hp=99 so nobody dies early, market=1, deck=3)",
           [(f"turns={t}", Cfg(hp=99, hand=3, market=(3,), start=(0, 0, 1),
                               turn_cap=t)) for t in range(1, 7)])
    ladder("B) market size (hp=99, turns=3, deck=3)",
           [(f"market={n}", Cfg(hp=99, hand=3, market=(3, 6, 4, 5)[:n],
                                start=(0, 0, 1), turn_cap=3)) for n in range(1, 5)])
    ladder("C) hand size (hp=99, turns=3, market=1, deck=4)",
           [(f"hand={h}", Cfg(hp=99, hand=h, market=(3,), start=(0, 0, 1, 2),
                              turn_cap=3)) for h in (2, 3, 4, 5)])


def verdict() -> None:
    print("--- verdict ---")
    print("""
Turns cost ~115x each, and that rate is stable across the whole ladder. The
market is nearly free (4 cards cost 4.6x over 1) and HP only matters through
how many turns a game lasts. So the binding question is: how few turns can a
Hero Realms variant have and still BE a deckbuilder?

A bought card enters the discard pile. With a 4-card deck and a 3-card hand it
becomes drawable only after a reshuffle, which is turn 2 for its owner - turn 5
or 6 of the game before it can be played and matter. Below that, "deckbuilding"
is buying cards you never see, and none of the three questions this was meant
to answer (exploitability of the shipped gate, whether the override gate
survives a best response, whether root narrowing survives) is even posed.

Six turns, one market card, canonical order: 320,479,021,729 histories = 2.03
years. Four market cards multiply that by ~4.6, giving ~1.5e12 histories, about
a decade of best response. The variants that DO fit in minutes - 3 turns, or a
single market card - cannot pose the questions.

So: exploitability is not computable at a scale where it says anything about
this project. Stop here. The nearest thing that keeps the pool-independence
property is a LEARNED best response against the frozen shipped policy, in the
real engine, which needs no reimplementation and therefore carries none of the
parity risk that the Ruby bug and the phase ratchet are warnings about.
""".strip())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", nargs="?", default="all",
                    choices=["all", "full", "infostates", "reference",
                             "canonical", "growth", "verdict"])
    ap.add_argument("--games", type=int, default=60)
    args = ap.parse_args()

    def sep():
        print("\n" + "=" * 78 + "\n")

    if args.stage in ("all", "full"):
        stage0_full_game(args.games)
    if args.stage in ("all", "infostates"):
        sep(); stage0_infostates(400)
    if args.stage in ("all", "reference"):
        sep()
        try:
            stage0_reference()
        except ImportError:
            print("open_spiel not installed; `pip install open_spiel` for this stage.")
    if args.stage in ("all", "canonical"):
        sep(); stage1_canonical()
    if args.stage in ("all", "growth"):
        sep(); stage1_growth()
    if args.stage in ("all", "verdict"):
        sep(); verdict()


if __name__ == "__main__":
    sys.setrecursionlimit(200_000)
    main()
