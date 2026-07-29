from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import math
import random
from typing import Any

from hero_engine import (
    FIRE_GEM,
    HRGame,
    _deck_gold_density,
    _has_ally_payload,
    _should_self_sacrifice,
    has_ally,
    play_card,
    buy_card,
    expend_champion,
)
from web.opponent_profiles import (
    PROFILE_NAMES,
    inferred_profile,
    inferred_profile_posterior,
    profile_buy_action,
)


@dataclass
class Node:
    action: dict[str, Any] | None
    parent: "Node | None" = None
    visits: int = 0
    # Bounded utility used by UCB and robust-child selection. Keeping it on a
    # fixed scale prevents terminal +/-10,000 leaf scores from flattening every
    # ordinary HP difference into numerical noise.
    reward: float = 0.0
    # Untransformed leaf score, retained for the UI and benchmark diagnostics.
    raw_reward: float = 0.0
    children: list["Node"] = None
    untried_actions: list[dict[str, Any]] = None
    # Retained in the node payload for search diagnostics and older callers.
    # Root-only information-set search creates bot children only.
    actor: str = "bot"
    # One bounded utility per complete common-random-number world. Populated
    # only by paired root search so candidate-minus-baseline uncertainty can be
    # estimated without pretending independent rollouts are paired samples.
    paired_utilities: list[float] = None

    def __post_init__(self) -> None:
        self.children = [] if self.children is None else self.children
        self.untried_actions = [] if self.untried_actions is None else self.untried_actions
        self.paired_utilities = [] if self.paired_utilities is None else self.paired_utilities

    def uct_score(self, exploration: float = 1.35, lo: float = 0.0, hi: float = 1.0,
                  maximize: bool = True) -> float:
        """UCT with the exploitation term normalised into [0, 1].

        The production search stores bounded utility directly and passes the
        fixed [0, 1] range. Legacy raw-mode A/Bs still use their observed
        reward range, so the normalisation remains here rather than being
        baked into the node.
        """
        if self.visits == 0:
            return float("inf")
        assert self.parent is not None
        span = hi - lo
        exploit = (self.reward / self.visits - lo) / span if span > 1e-9 else 0.5
        # Minimax alternation: the opponent is not trying to help. Without this
        # the tree picked the opponent's replies to maximise the bot's score, so
        # deeper search planned against a cooperative opponent and got worse.
        if not maximize:
            exploit = 1.0 - exploit
        return exploit + exploration * math.sqrt(math.log(self.parent.visits + 1) / self.visits)


def _card_value(card) -> float:
    return (
        card.get("combat", 0) * 3.0
        + card.get("gold", 0) * 2.5
        + card.get("draw", 0) * 4.0
        + card.get("health", 0) * 1.2
        + card.get("opponent_discard", 0) * 2.0
        + card.get("stun", False) * 1.5
        + card.cost * 0.25
    )


def _board_value(board) -> float:
    total = 0.0
    for champion in board:
        if champion.alive:
            total += champion.card.health * 0.9 + champion.current_health * 0.5 + champion.card.guard * 1.5
            total += champion.card.get("combat", 0) * 1.2 + champion.card.get("gold", 0) * 0.9
    return total


# A turn draws 5 cards, so deck quality is felt 5 cards at a time. _card_value
# is denominated in resource points (a 2-combat card scores 6.0, so ~3 points
# per combat), and 1 combat converts to roughly 1 damage, which the health term
# below prices at 10. So one point of average card quality is worth about
# 5 * 10/3 in this scale. Derived rather than tuned; it is the single knob most
# worth sweeping empirically.
DECK_QUALITY_WEIGHT = 5 * 10 / 3


def _deck_quality(player) -> float:
    """Average value of the cards a player draws from.

    Deliberately a mean, not a sum. Total value rewards hoarding: a deck of a
    thousand Gold would outscore five strong cards, when in reality it is far
    worse, because you only ever see 5 cards a turn and every junk card
    displaces a good one. Using the mean makes a purchase pay only if the card
    beats what you already draw, and makes banishing a Gold a gain.

    Location is irrelevant - deck, hand, and discard all come around again.
    Champions in play are excluded and priced by _board_value instead: they sit
    on the board rather than diluting the draw pool.
    """
    cards = player.deck + player.hand + player.discard
    if not cards:
        return 0.0
    return sum(_card_value(card) for card in cards) / len(cards)


# Starting deck gold density (7 Gold among 10 cards, 1 gold each) is 0.7. The
# discount below divides by 4x this, so a fresh deck sits at a mild discount
# (0.8) rather than a severe one (0.5). At 0.5 the very first buy decision of
# every game already halved gold's weight before a single purchase, and against
# a combat weight in the same range that made a 1-cost, 3-combat, zero-economy
# card (Spark) outscore a 1-cost, 2-gold card (Taxation) even at full opponent
# health - real cards, not synthetic test ones. The rollout would then never
# build an economy at all. Verified: Spark scored 5.7 against Taxation's 2.2
# under the 1x scale; recalibrated here.
STARTING_GOLD_DENSITY = 0.7
GOLD_DISCOUNT_SCALE = STARTING_GOLD_DENSITY * 4.0

# Ids of the four starting cards. _card_score in hero_engine.py scores these as
# the worst cards in any deck, so they are what sacrifice/discard effects
# remove first - the concrete thing a sacrifice effect's thinning value is
# thinning *of*.
_STARTING_JUNK_IDS = {"gold", "shortsword", "dagger", "ruby"}

# Floor for ally value when the buyer owns no card of that faction yet. Not
# zero: buying the first card of a faction is how a faction stack starts, and
# ally-bearing cards are a third of the pool, so pricing them at their base
# effects alone would never let a stack get going.
_ALLY_FLOOR = 0.15


def _junk_count(player) -> int:
    cards = player.deck + player.hand + player.discard
    return sum(1 for c in cards if c.id in _STARTING_JUNK_IDS)


def _resource_weights(session, seat: str) -> dict[str, float]:
    """Per-resource weights, scaled by the two things a real player conditions
    on: how close the opponent is to dead, and how urgently the buyer needs
    healing. Returned as a dict rather than inlined so ally-triggered bonuses
    (ally_combat, ally_gold, ...) can reuse the same weights as their base
    counterparts.
    """
    opponent = session.player if seat == "bot" else session.bot
    buyer = session.bot if seat == "bot" else session.player
    opp_hp_ratio = min(max(opponent.hp, 0), HRGame.STARTING_HP) / HRGame.STARTING_HP
    own_hp_ratio = min(max(buyer.hp, 0), HRGame.STARTING_HP) / HRGame.STARTING_HP

    gold_discount = 1.0 / (1.0 + max(_deck_gold_density(buyer), 0.0) / GOLD_DISCOUNT_SCALE)

    return {
        # 2.0 at full opponent health, ramping to 4.0 near lethal: closing out
        # a game matters more than incremental damage, but not so much more
        # that it swamps everything else the way the first version did.
        "combat": 2.0 + (1.0 - opp_hp_ratio) * 2.0,
        # 3.0 at full opponent health, decaying to 1.5 near lethal, discounted
        # by the buyer's own gold density (diminishing returns on gold
        # specifically - see _deck_gold_density's own docstring for why it
        # can't be overall deck quality instead).
        "gold": (1.5 + opp_hp_ratio * 1.5) * gold_discount,
        # Card advantage is close to context-independent: more selection is
        # good whether ahead or behind.
        "draw": 4.0,
        # 1.5 at full own health (low urgency) ramping to 5.0 near own death:
        # a heal is worth roughly what it costs the opponent to deal that
        # much damage, so this tracks the same shape as combat_weight but on
        # the buyer's own health instead of the opponent's.
        "health": 1.5 + (1.0 - own_hp_ratio) * 3.5,
    }


def _ally_certainty(session, seat: str, card) -> float:
    """How much of an ally_* bonus to count, given board state right now.

    1.0 if the buyer already has a champion of the required faction in play
    (the bonus is real and immediate), else a partial credit reflecting that
    the ally is not guaranteed but not worthless either - a fixed discount
    rather than 0, since ally_faction cards are common enough that ignoring
    the bonus entirely would undervalue roughly a third of the card pool
    (36 of the cards surveyed carry ally_faction).
    """
    faction = card.effects.get("ally_faction", "")
    if not faction:
        return 0.0
    buyer = session.bot if seat == "bot" else session.player

    # A champion of that faction on the board is permanent: the ally is
    # guaranteed to be live every turn this card is drawn.
    if faction in buyer.allies():
        return 1.0

    # Otherwise the ally only fires if another card of the same faction turns
    # up in play alongside it, so the value depends on how concentrated the
    # deck is in that faction - the actual synergy signal. A flat constant
    # here priced a first Necros card the same as a seventh, which is what
    # made faction-stacking invisible to the buy policy.
    #
    # A turn draws 5 cards, so approximate the chance that at least one of the
    # other 4 is the same faction. This matters more now that the engine
    # triggers action-to-action allies correctly (see has_ally).
    owned = buyer.deck + buyer.hand + buyer.discard
    if not owned:
        return _ALLY_FLOOR
    same = sum(1 for c in owned if c.faction == faction)
    if not same:
        return _ALLY_FLOOR
    chance = 1.0 - (1.0 - same / len(owned)) ** 4
    return min(1.0, max(_ALLY_FLOOR, chance))


def _thinning_value(player, count: int) -> float:
    """Value of permanently removing the `count` worst cards from a deck.

    Priced as the actual improvement in _deck_quality (mean value of the cards
    you draw from), on the same DECK_QUALITY_WEIGHT scale everything else
    uses, rather than a flat per-card constant. Thinning is the one effect
    whose value is *entirely* about what is left behind: removing a Gold from
    a 10-card starting deck is a large permanent gain, and removing the same
    Gold from a 30-card deck that has already been thinned is a small one. A
    constant could not express that, and undervalued the first sacrifice
    outlet - which in practice is the card that makes a deck work.

    Compounding is deliberately not modelled: this prices one activation, not
    the repeatable engine a sacrifice *champion* provides every turn.
    """
    cards = player.deck + player.hand + player.discard
    if not cards or count <= 0:
        return 0.0
    values = sorted(_card_value(c) for c in cards)
    kept = values[count:]
    if not kept:
        return 0.0
    before = sum(values) / len(values)
    after = sum(kept) / len(kept)
    return max(0.0, after - before) * DECK_QUALITY_WEIGHT


def _enabler_value(session, seat: str, card, weights: dict[str, float]) -> float:
    """Value of a card as an ally *enabler* for cards the buyer already owns.

    A card participates in faction synergy two ways: its own ally ability
    firing (priced by _ally_certainty), and counting as a faction card that
    turns on everything else of that faction. 18 of the 19 market cards with
    no printed ally ability of their own still have a faction, so they are
    pure enablers - and scoring only the first way rated them identically to
    Fire Gem, the single market card with no faction at all.

    That is exactly why Fire Gem is a weak buy unless the market is all
    expensive: it can never enable anything, while any faction card of
    similar cost carries this on top of its printed effects.

    Priced as the increase in trigger probability for each same-faction ally
    card already owned, using the same 5-card-draw approximation as
    _ally_certainty.
    """
    faction = card.faction
    if not faction:
        return 0.0
    buyer = session.bot if seat == "bot" else session.player
    owned = buyer.deck + buyer.hand + buyer.discard
    if not owned:
        return 0.0

    partner_value = 0.0
    same_faction = 0
    for owned_card in owned:
        if owned_card.faction != faction:
            continue
        same_faction += 1
        if _has_ally_payload(owned_card):
            partner_value += (
                owned_card.get("ally_combat", 0) * weights["combat"]
                + owned_card.get("ally_gold", 0) * weights["gold"]
                + owned_card.get("ally_draw", 0) * weights["draw"]
                + owned_card.get("ally_health", 0) * weights["health"]
            )
    if partner_value <= 0.0:
        return 0.0

    total = len(owned)
    before = 1.0 - (1.0 - same_faction / total) ** 4
    after = 1.0 - (1.0 - (same_faction + 1) / (total + 1)) ** 4
    return max(0.0, after - before) * partner_value


def _sacrifice_bonus(session, seat: str, card, weights: dict[str, float] | None = None) -> float:
    """Value of a card's optional sacrifice/thinning effects.

    `weights` may be passed in when scoring several candidates from the same
    position: _resource_weights scans the whole deck for gold density, and it
    is identical for every card in one decision.

    Every printed sacrifice effect reads "you may sacrifice" - hero_engine.py
    only takes it when _should_self_sacrifice/_worth_sacrificing say it is
    actually worth it (a guard would absorb combat for nothing, or nothing in
    hand/discard is junk). This reuses those exact predicates against the
    buyer's current state, rather than assuming the old unconditional
    guarantee, which would price a bonus the engine would actually decline.
    It is still only an estimate of what happens when the card is eventually
    played, since hand/discard contents and the opponent's board will have
    moved on by then.

    sacrifice_card/sacrifice_for_combat/sacrifice_up_to remove the worst card
    from hand or discard - _find_worst_idx always prefers the four starting
    cards (see _card_score in hero_engine.py) - so their thinning value is
    scaled by how much of that junk is actually left to remove: thinning the
    last weak card in a lean deck is worth more than the fifth in a deck
    still full of them, and once the junk is gone the effect has nothing left
    to remove (matching the engine, which now declines rather than forcing it).
    """
    buyer = session.bot if seat == "bot" else session.player
    opponent = session.player if seat == "bot" else session.bot
    if weights is None:
        weights = _resource_weights(session, seat)
    bonus = 0.0

    sac_combat = card.get("sacrifice_combat", 0)
    if sac_combat and _should_self_sacrifice(buyer, opponent, requires_open_combat=True):
        bonus += sac_combat * weights["combat"]

    sac_count = 0
    if card.effects.get("sacrifice_card", False):
        sac_count = 1
    elif card.get("sacrifice_for_combat", 0) > 0:
        sac_count = 1
        # _find_worst_idx (hero_engine.py) always prefers the four starting
        # cards over anything purchased, so "is there any junk at all" is an
        # exact proxy for "would _worth_sacrificing accept the worst pick."
        if _junk_count(buyer) > 0:
            bonus += card.get("sacrifice_for_combat", 0) * weights["combat"]
    elif card.get("sacrifice_up_to", 0) > 0:
        sac_count = card.get("sacrifice_up_to", 0)

    if sac_count:
        bonus += _thinning_value(buyer, sac_count)
    return bonus


def _holistic_card_score(session, seat: str, card, weights: dict[str, float] | None = None) -> float:
    """Context-dependent value of a candidate purchase, across the whole
    effect surface rather than only gold and combat.

    evaluate_state deliberately asserts no fixed resource exchange rate and
    leaves that to the rollout, but the rollout has to actually play turns to
    generate that signal, and its default policy is what determines how good
    those simulated games are. A policy that only weighs gold against combat
    misses roughly half the card pool: ally_* effects appear on 36+10+10+4+2
    cards and sacrifice_* effects on 13, and neither was priced at all before
    this. This stays out of evaluate_state itself - it only shapes how
    rollouts are simulated, sharpening the reward search assigns to root
    candidates, not asserting a fixed price at the point that gets searched.

    `weights` may be passed in when scoring several candidates from the same
    position - see _best_buy_action.
    """
    if weights is None:
        weights = _resource_weights(session, seat)
    or_choice = card.get("or_choice", [])

    score = card.get("draw", 0) * weights["draw"]
    if or_choice:
        # These branches are mutually exclusive at resolution time (see
        # expend_champion's or_choice handling in hero_engine.py), so summing
        # every listed field double-counts value that can never all be
        # realised in one activation. Take the best available branch instead.
        #
        # per_champion_health is scored separately rather than through
        # weights.get(kind, 0.0): weights has no such key, so folding it into
        # the same lookup silently dropped it from every or_choice comparison
        # (e.g. Tithe Priest's {gold:1, or_choice:['gold','per_champion_health'],
        # per_champion_health:1} always scored as gold-only, regardless of how
        # many champions were on board).
        buyer = session.bot if seat == "bot" else session.player
        champ_count = len([bc for bc in buyer.board if bc.alive])
        branch_scores = [card.get(kind, 0) * weights[kind] for kind in or_choice if kind in weights]
        if "per_champion_health" in or_choice:
            branch_scores.append(card.get("per_champion_health", 0) * champ_count * weights["health"])
        score += max(branch_scores, default=0.0)
    else:
        score += card.get("combat", 0) * weights["combat"]
        score += card.get("gold", 0) * weights["gold"]
        score += card.get("health", 0) * weights["health"]

    ally_scale = _ally_certainty(session, seat, card)
    if ally_scale:
        score += ally_scale * (
            card.get("ally_combat", 0) * weights["combat"]
            + card.get("ally_gold", 0) * weights["gold"]
            + card.get("ally_draw", 0) * weights["draw"]
            + card.get("ally_health", 0) * weights["health"]
            + card.get("ally_opponent_discard", 0) * 2.0
        )

    score += _sacrifice_bonus(session, seat, card, weights)
    score += _enabler_value(session, seat, card, weights)
    score += card.get("opponent_discard", 0) * 2.0
    score += card.get("sacrifice_opponent_discard", 0) * 2.0
    if card.get("stun", False):
        score += 1.5

    # Combo-enabling utility effects (recycle, reanimate, prepare, to_hand,
    # top_of_deck): their real value depends on the rest of the deck in ways
    # this does not model. A small flat credit acknowledges they are rarely
    # dead text rather than pricing them properly.
    for flag in ("recycle", "reanimate", "prepare", "to_hand", "top_of_deck"):
        if card.get(flag, False):
            score += 1.5

    if card.card_type == "champion":
        score += card.health * 0.5 + (3.0 if card.guard else 0.0)
    score -= card.cost * 0.3
    return score


def _best_buy_action(session, buy_actions: list[dict[str, Any]]) -> dict[str, Any]:
    seat = session.active_player

    def card_for(action):
        idx = int(action.get("marketIndex", -1))
        if idx == 5:
            return FIRE_GEM
        if 0 <= idx < 5:
            return session.market.row_cards()[idx]
        return None

    scored = [(a, card_for(a)) for a in buy_actions]
    scored = [(a, c) for a, c in scored if c is not None]
    if not scored:
        return buy_actions[0]
    # Computed once for the whole decision rather than per candidate:
    # _resource_weights scans the entire deck for gold density, and the result
    # depends only on the position, not on which card is being scored. It was
    # being recomputed twice per candidate (once here, once inside
    # _sacrifice_bonus).
    weights = _resource_weights(session, seat)
    return max(scored, key=lambda pair: _holistic_card_score(session, seat, pair[1], weights))[0]


def _adaptive_buy_action(session, buy_actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Use visible opponent draw engines to tilt the rollout toward tempo.

    A fixed draw-heavy buy rule helps against balanced opponents but overreacts
    to economic decks.  Only a live opponent champion that actually draws is a
    public signal strong enough to change the weights: when one exists, value
    immediate combat/discard more; otherwise retain balanced draw value.
    """
    opponent = session.player if session.active_player == "bot" else session.bot
    draw_engine = sum(
        champion.card.effects.get("draw", 0)
        for champion in opponent.board if champion.alive
    )
    gold_weight, combat_weight, draw_weight = (
        (1.0, 3.0, 1.0) if draw_engine >= 1 else (2.0, 2.0, 3.0)
    )

    def card_for(action):
        idx = int(action.get("marketIndex", -1))
        if idx == 5:
            return FIRE_GEM
        if 0 <= idx < 5:
            return session.market.row_cards()[idx]
        return None

    scored = []
    for action in buy_actions:
        card = card_for(action)
        if card is None:
            continue
        score = (
            card.get("gold", 0) * gold_weight
            + card.get("combat", 0) * combat_weight
            + card.get("draw", 0) * draw_weight
            + card.get("health", 0)
            + card.get("sacrifice_combat", 0) * 1.5
            + card.get("opponent_discard", 0) * 2.0
            + card.get("ally_opponent_discard", 0) * 2.0
        )
        if card.card_type == "champion":
            score += card.health + card.health // 2
        score -= card.cost // 2
        scored.append((action, score))
    return max(scored, key=lambda pair: pair[1])[0] if scored else buy_actions[0]


WIN_SCORE = 10_000.0

# UCB needs rewards on a stable scale. The legacy raw mode remains useful for
# controlled A/Bs; the default bounds nonterminal positions smoothly between
# terminal loss/win so one sampled terminal cannot erase all HP signal.
MCTS_UTILITY_MODE = "bounded"

# turn_number increments once per seat, so this is ~8 full rounds. The horizon
# has to be long enough for a bought card to be shuffled in, drawn, and used,
# or search-priced evaluation cannot see what a purchase bought. 16 was the
# strongest historical candidate and remains the fair-search default; use
# hero_horizon_ab.py to revalidate it when changing the rollout or budget.
ROLLOUT_TURNS = 16

# "search" prices nothing and lets rollouts decide; "shaped" uses the static
# weights below. Kept switchable so the two can be benchmarked head to head.
EVAL_MODE = "search"

# Phases worth spending search on. Play and champion phases are auto-resolved
# greedily; see the note in choose_bot_action.
SEARCHED_PHASES = ("buy", "combat")

# "static" is the original policy (highest legal_actions priority:
# cost + combat*2 + gold*2 + draw*2, fixed regardless of game state);
# "situational" uses _holistic_card_score.
#
# Root/fallback and rollout buying deliberately use different policies. The
# static policy is the stronger deterministic player (43/80 vs adaptive 36/80
# on a matched block), while adaptive continuations gave MCTS a better opponent
# and future-turn model. Keeping one global policy forced a false tradeoff.
#
#   pre-engine-fixes    static 20.0%  situational 18.8%
#   post-engine-fixes   static 20.6%  situational 18.1%
#   current            static 22.5%  situational 15.8%
#
# This is the known MCTS result that a *stronger* rollout policy does not
# imply a stronger search: a more deterministic, more greedy default policy
# narrows the distribution of simulated outcomes and biases the value
# estimates, and that costs more than the better play buys. _holistic_card_score
# is not wasted - it decomposes into named, explainable terms (opponent-HP
# urgency, ally certainty, thinning value), which is what a coach needs to
# justify a recommendation. It belongs in the explanation layer, not in the
# rollout.
# "adaptive" is draw-engine aware: it only tilts toward immediate combat when
# a visible opposing champion actually produces draw.
BUY_POLICY = "static"
# Public purchase evidence safely routes continuation buying between the two
# complementary rollout policies.  Unknown/champion opponents retain the
# incumbent adaptive policy; balanced/aggressive/economic observations use the
# situational continuation that won those matched cells.  Across four disjoint
# fixed-effort blocks this raised the worst profile from 25/80 to 27/80 and
# improved every profile (112/320 vs 105/320 overall).
ROLLOUT_BUY_POLICY = "adaptive"

# The benchmark opposition has four deterministic buy profiles. Production
# search samples from a smoothed posterior over those profiles using only
# immutable public purchases. This avoids overcommitting to the wrong hard-MAP
# profile when aggressive and champion purchase traces are observationally
# similar, while retaining paired fairness within each determinized world.
OPPONENT_ROLLOUT_POLICY = "posterior"  # "adaptive", "inferred", "posterior", or "mixture"
OPPONENT_MODEL_MIN_OBSERVATIONS = 2

# Root-only ISMCTS is a stochastic bandit: two purchases evaluated against
# different sampled hidden hands can differ for reasons unrelated to the
# purchase. Paired mode samples one *fair* hidden world and rolls every public
# root action from a clone of it, so their difference is less noisy. It won the
# fixed-effort A/B, while independent UCB remains the fallback for larger root
# action sets where a complete paired round would consume the search slice.
ROOT_SAMPLING_MODE = "paired"  # "independent" or "paired"
PAIRED_ROOT_MAX_ACTIONS = 3

# At the interactive simulation count, spreading root visits across every
# affordable market card plus pass is substantially worse than the static
# rollout policy: most candidates receive only one noisy hidden-world sample.
# Keep the three strongest public buy candidates at the root. This is progressive
# widening, not an engine rule: legal_actions and rollouts still retain the
# complete choice set. With an affordable buy, pass is omitted because unused
# gold resets at end of turn. Set to 0 for the legacy all-actions A/B control.
MCTS_BUY_ROOT_WIDTH = 3

# Progressive widening must retain the heuristic action that the override gate
# compares against. With adaptive/situational buying that action may not be one
# of the static-priority top three; excluding it makes the baseline unsampled and
# forces _guarded_root_choice to fall back without a meaningful comparison.
MCTS_BUY_INCLUDE_BASELINE = True

# MCTS is an advisor over a strong deterministic policy, not permission to
# replace it on sampling noise. Require a material bounded-utility improvement
# before choosing a different root action. The shipped width+gate configuration
# beat the same-seat heuristic 49/80 to 39/80 on two fresh production-path
# blocks (discordant wins 12-2, exact paired p=.013). Set to -1.0 for the
# unguarded A/B control.
MCTS_OVERRIDE_MARGIN = 0.10

# "margin" preserves the validated fixed threshold. "confidence" uses the
# paired per-world differences already generated by common-random-number root
# rounds, requiring a positive one-sided lower confidence bound.
MCTS_OVERRIDE_GATE = "margin"  # "margin" or "confidence"
MCTS_CONFIDENCE_Z = 1.0
MCTS_CONFIDENCE_MIN_WORLDS = 4
MCTS_CONFIDENCE_MIN_EFFECT = 0.0


# Weight on standing board value (own minus enemy) added to the otherwise
# pure-HP-diff search eval. 0.0 keeps the original behaviour byte-for-byte.
#
# The measured motivation: with a short horizon, a non-guard enemy
# champion whose expend makes *gold* never touches HP in time, so pure HP-diff
# is indifferent to killing it - MCTS clears Broelyn (2 gold/turn) 0% of the
# time while the greedy fallback clears it 100%. A champion whose expend deals
# combat is already priced (the rollout takes the damage). This term prices the
# recurring value HP-diff misses, so denial gets valued.
DENY_BOARD_WEIGHT = 0.0



def _champ_recurring_value(bc) -> float:
    """Per-turn output a champion keeps generating while it lives - the part a
    short HP-diff horizon cannot see. Combat is included for consistency though
    the rollout already prices it; gold/draw are the terms that were invisible."""
    if not bc.alive:
        return 0.0
    e = bc.card.effects
    return (e.get("gold", 0) * 1.0 + e.get("draw", 0) * 2.0
            + e.get("combat", 0) * 1.0 + e.get("health", 0) * 0.5)


def _board_balance(session) -> float:
    own = sum(_champ_recurring_value(bc) for bc in session.bot.board)
    enemy = sum(_champ_recurring_value(bc) for bc in session.player.board)
    return own - enemy


def evaluate_state(session) -> float:
    """Score a position by the win condition, plus (optionally) standing board
    value.

    The HP-diff core prices gold, combat, and draw at exactly what the rollout
    converts them into - the gold-to-combat exchange rate is situational and any
    fixed weight is wrong somewhere. That is sound only because _rollout plays
    whole turns for both seats; even so, a short horizon is too short to
    convert a denied enemy economy champion into HP, which DENY_BOARD_WEIGHT
    corrects when non-zero.
    """
    if session.winner == "bot":
        return WIN_SCORE
    if session.winner == "player":
        return -WIN_SCORE
    score = (session.bot.hp - session.player.hp) * 10.0
    if DENY_BOARD_WEIGHT:
        score += DENY_BOARD_WEIGHT * _board_balance(session)
    return score


def evaluate_state_shaped(session) -> float:
    """Hand-priced evaluation, retained for A/B comparison against search."""
    # Preserve exact terminal utility for every evaluation mode.  Without
    # this, hybrid leaves that use the shaped evaluator can rank a finished
    # loss/win by its ordinary board/economy score and prefer a terminal loss
    # over a live continuation.
    if session.winner == "bot":
        return WIN_SCORE
    if session.winner == "player":
        return -WIN_SCORE
    player = session.bot
    opponent = session.player

    score = (player.hp - opponent.hp) * 10.0
    score += (_deck_quality(player) - _deck_quality(opponent)) * DECK_QUALITY_WEIGHT
    score += _board_value(player.board) - _board_value(opponent.board)
    score += player.gold * 0.5
    score += player.combat * 1.5
    return score


def _leaf_value(session) -> float:
    eval_mode = EVAL_MODE
    if eval_mode == "hybrid":
        inferred = inferred_profile(session, OPPONENT_MODEL_MIN_OBSERVATIONS)
        eval_mode = "shaped" if inferred in {"economic", "champion"} else "search"
    if eval_mode == "shaped":
        return evaluate_state_shaped(session)
    return evaluate_state(session)


def _search_utility(raw_score: float) -> float:
    """Map a rollout score to a stable [0, 1] UCB reward.

    Terminal leaves stay exact 0/1. Nonterminal scores are predominantly
    health differences (normally [-500, 500]), so a smooth bounded mapping
    preserves their ordering without allowing a single terminal sample to
    expand the UCB normalisation range by two orders of magnitude.
    """
    if MCTS_UTILITY_MODE == "raw":
        return raw_score
    if raw_score >= WIN_SCORE:
        return 1.0
    if raw_score <= -WIN_SCORE:
        return 0.0
    return 0.5 + 0.4 * math.tanh(raw_score / 250.0)


def legal_actions(session) -> list[dict[str, Any]]:
    return session.legal_actions()


def apply_action(session, action: dict[str, Any]) -> None:
    action_type = action["type"]
    if action_type == "play_card":
        session.play_card(action["cardId"], action.get("stunTargetIndex"))
    elif action_type == "expend_champion":
        session.expend_champion_action(action["championId"], action.get("stunTargetIndex"))
    elif action_type == "buy_card":
        session.buy_card_action(int(action["marketIndex"]))
    elif action_type == "attack_target":
        session.attack_target_action(action["target"], action.get("championId"))
    elif action_type == "advance_phase":
        session.advance_phase()
    else:
        raise ValueError(f"Unsupported action: {action_type}")


def _sorted_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(actions, key=lambda item: item.get("priority", 0), reverse=True)


def _action_summary(action: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "type": action.get("type"),
        "label": action.get("label", action.get("type", "Action")),
        "cardId": action.get("cardId"),
        "marketIndex": action.get("marketIndex"),
        "championId": action.get("championId"),
        "stunTargetIndex": action.get("stunTargetIndex"),
        "target": action.get("target"),
    }
    for key in ("score", "visits", "averageScore", "priority"):
        if key in action:
            summary[key] = action[key]
    return summary


def _champion_threat_value(champion, owner) -> float:
    """Public, repeatable value for choosing a champion to remove.

    Targeting happens before search in play/champion phases, so it must not
    inspect the opponent's hidden hand or deck.  Printed cost and the visible
    champion's recurring output give a stable ranking, while currently-live
    ally text is also public from the board.
    """
    card = champion.card
    value = float(card.cost) + _champ_recurring_value(champion)
    if has_ally(card, owner):
        value += (
            card.get("ally_combat", 0)
            + card.get("ally_gold", 0)
            + card.get("ally_draw", 0) * 2.0
            + card.get("ally_health", 0) * 0.5
            + card.get("ally_opponent_discard", 0) * 1.5
        )
    return value


def _best_stun_target_action(session, first_action: dict[str, Any],
                             phase_actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the normal play order, but choose the best legal stun target."""
    if "stunTargetIndex" not in first_action:
        return first_action

    action_type = first_action["type"]
    identity_key = "cardId" if action_type == "play_card" else "championId"
    same_effect = [
        action for action in phase_actions
        if action["type"] == action_type
        and action.get(identity_key) == first_action.get(identity_key)
        and "stunTargetIndex" in action
    ]
    opponent = session.player if session.active_player == "bot" else session.bot
    targets = session._attack_targets(opponent)

    def target_value(action: dict[str, Any]) -> float:
        index = action.get("stunTargetIndex")
        if not isinstance(index, int) or not 0 <= index < len(targets):
            return float("-inf")
        return _champion_threat_value(targets[index], opponent)

    return max(same_effect, key=target_value, default=first_action)


def _heuristic_rollout_action(session, actions: list[dict[str, Any]] | None = None,
                              buy_policy: str | None = None) -> dict[str, Any]:
    """Greedy default policy. `actions` may be passed in by a caller that has
    already computed legal_actions for this state (the rollout loop does), to
    avoid rebuilding the action dicts a second time.

    session.legal_actions() already returns its result sorted by priority
    descending, using the same key _sorted_actions applies, so re-sorting here
    was a no-op - verified across 4999 states.
    """
    if actions is None:
        actions = legal_actions(session)
    if not actions:
        return {"type": "advance_phase"}

    phase = session.phase
    selected_buy_policy = BUY_POLICY if buy_policy is None else buy_policy
    if phase == "play":
        first_play = next((action for action in actions if action["type"] == "play_card"), None)
        if first_play is not None:
            return _best_stun_target_action(session, first_play, actions)
    elif phase == "champion":
        first_expend = next((action for action in actions if action["type"] == "expend_champion"), None)
        if first_expend is not None:
            return _best_stun_target_action(session, first_expend, actions)
    elif phase == "buy":
        buy_actions = [a for a in actions if a["type"] == "buy_card"]
        if buy_actions:
            if selected_buy_policy == "static":
                chosen = buy_actions[0]  # already highest-priority: actions is pre-sorted
            elif selected_buy_policy == "adaptive":
                chosen = _adaptive_buy_action(session, buy_actions)
            else:
                chosen = _best_buy_action(session, buy_actions)
            return chosen
    elif phase == "combat":
        # Priority is 10 - current_health for a champion (higher for a weaker
        # one) and player.combat for the player, so a target list containing
        # both a low-health champion and the player is not reliably ordered
        # by which one actually matters. That let the plain priority-sorted
        # pick snipe a 3-health champion instead of taking a simultaneously
        # available lethal hit - a minimal safety check, not a broader
        # valuation change: earlier this session, giving the rollout a
        # "smarter" default policy for buying made search measurably worse,
        # so this only guards against missing a game-ending hit.
        buyer = session.bot if session.active_player == "bot" else session.player
        opponent = session.player if session.active_player == "bot" else session.bot
        if buyer.combat >= opponent.hp:
            lethal = next((a for a in actions if a["type"] == "attack_target"
                          and a.get("target") == "player"), None)
            if lethal is not None:
                return lethal
        face = next((a for a in actions if a["type"] == "attack_target"
                     and a.get("target") == "player"), None)
        champion_actions = [a for a in actions if a["type"] == "attack_target"
                            and a.get("target") == "champion"]
        targets_by_id = {
            str(champion.instance_id): champion
            for champion in opponent.board if champion.alive
        }

        # No face action means a guard is alive. Clear the weakest one first;
        # if it survives, the remaining combat expires anyway at end of turn.
        if face is None and champion_actions:
            return min(champion_actions, key=lambda action: (
                targets_by_id.get(action.get("championId")).current_health
                if action.get("championId") in targets_by_id else float("inf")
            ))

        # Champion damage resets next turn. With no guard, only spend combat
        # on an undefended champion if it can be finished now; otherwise send
        # it to the opposing player instead of throwing it away as chip damage.
        killable = [
            action for action in champion_actions
            if action.get("championId") in targets_by_id
            and targets_by_id[action["championId"]].current_health <= buyer.combat
        ]
        if killable:
            return min(killable, key=lambda action: targets_by_id[action["championId"]].current_health)
        if face is not None:
            return face
        if champion_actions:
            return champion_actions[0]
    return actions[0]


def _combat_search_actions(session, attacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep MCTS only for combat target choices that are not forced by rules.

    Lethal face damage, clearing a blocking guard, and sending otherwise
    unusable combat face are deterministic tactical outcomes.  Searching those
    branches spends the shallow root budget rediscovering rules.  Preserve
    multiple guard targets and multiple currently-killable champions, where
    target identity can still be strategic.
    """
    buyer = session.bot if session.active_player == "bot" else session.player
    opponent = session.player if session.active_player == "bot" else session.bot
    face = [action for action in attacks if action.get("target") == "player"]
    champions = [action for action in attacks if action.get("target") == "champion"]

    if face and buyer.combat >= opponent.hp:
        return face[:1]
    if not face:
        # A guard is blocking; the engine only exposes guard targets here.
        return champions

    board = {
        str(champion.instance_id): champion
        for champion in opponent.board if champion.alive
    }
    killable = [
        action for action in champions
        if action.get("championId") in board
        and board[action["championId"]].current_health <= buyer.combat
    ]
    if killable:
        return killable
    return face[:1]


def _rollout(session, turn_limit: int | None = None, action_cap: int = 400,
             opponent_profile: str | None = None) -> float:
    """Play both seats forward greedily, then score the resulting position.

    This used to stop the moment the turn passed to the opponent, so the bot
    never simulated being hit and never saw a purchase come back around. Both
    seats are now played out. The bot retains its adaptive rollout policy; an
    observed opponent can instead use a public-information inferred profile.
    """
    # Read at call time, not bound as a default, so the constant stays tunable.
    turn_limit = ROLLOUT_TURNS if turn_limit is None else turn_limit
    if opponent_profile is None and OPPONENT_ROLLOUT_POLICY == "inferred":
        opponent_profile = inferred_profile(session, OPPONENT_MODEL_MIN_OBSERVATIONS)
    start_turn = session.turn_number
    steps = 0
    while (not session.winner
           and session.turn_number - start_turn < turn_limit
           and steps < action_cap):
        # Computed once and handed to the policy: this used to call
        # legal_actions here for the emptiness check and again inside
        # _heuristic_rollout_action, rebuilding every action dict twice.
        actions = legal_actions(session)
        if not actions:
            break
        if (opponent_profile is not None and session.active_player == "player"
                and session.phase == "buy"):
            action = profile_buy_action(session, actions, opponent_profile)
        else:
            rollout_buy_policy = ROLLOUT_BUY_POLICY
            if rollout_buy_policy == "routed":
                # Public purchase observations can identify the opponent's
                # broad economy profile after a few turns. Situational buying
                # is more useful against the three card-selection profiles;
                # retain adaptive buying while evidence is sparse or points
                # to the champion profile, where it is less reliable.
                rollout_buy_policy = "adaptive"
                if session.active_player == "bot" and session.phase == "buy":
                    inferred = inferred_profile(
                        session, OPPONENT_MODEL_MIN_OBSERVATIONS,
                    )
                    if inferred in {"balanced", "aggressive", "economic"}:
                        rollout_buy_policy = "situational"
            action = _heuristic_rollout_action(
                session, actions, buy_policy=rollout_buy_policy,
            )
        apply_action(session, action)
        steps += 1
    return _leaf_value(session)


def _sample_rollout_opponent_profile(session, search_rng: random.Random) -> str | None:
    if OPPONENT_ROLLOUT_POLICY == "mixture":
        return PROFILE_NAMES[search_rng.randrange(len(PROFILE_NAMES))]
    if OPPONENT_ROLLOUT_POLICY == "posterior":
        posterior = inferred_profile_posterior(
            session, OPPONENT_MODEL_MIN_OBSERVATIONS,
        )
        if posterior is None:
            return None
        draw = search_rng.random()
        cumulative = 0.0
        for profile in PROFILE_NAMES:
            cumulative += posterior[profile]
            if draw < cumulative:
                return profile
        return PROFILE_NAMES[-1]
    if OPPONENT_ROLLOUT_POLICY == "inferred":
        return inferred_profile(session, OPPONENT_MODEL_MIN_OBSERVATIONS)
    return None


def _action_key(action: dict[str, Any] | None) -> tuple:
    if action is None:
        return ()
    return (
        action.get("type"),
        action.get("cardId"),
        action.get("marketIndex"),
        action.get("championId"),
        action.get("stunTargetIndex"),
        action.get("target"),
    )


def _legal_keys(session) -> set[tuple]:
    return {_action_key(action) for action in legal_actions(session)}


def _root_search_actions(session, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply root-only progressive widening to noisy buy decisions."""
    if session.phase != "buy":
        return actions
    if MCTS_BUY_ROOT_WIDTH <= 0:
        return actions
    buy_actions = [action for action in actions if action["type"] == "buy_card"]
    if not buy_actions:
        return actions
    if not MCTS_BUY_INCLUDE_BASELINE:
        return buy_actions[:MCTS_BUY_ROOT_WIDTH]

    baseline = _heuristic_rollout_action(session, buy_actions)
    narrowed = [baseline]
    seen = {_action_key(baseline)}
    for action in buy_actions:
        if len(narrowed) >= MCTS_BUY_ROOT_WIDTH:
            break
        if _action_key(action) in seen:
            continue
        narrowed.append(action)
        seen.add(_action_key(action))
    return narrowed


def _root_candidates_from_children(root: Node, rank_by: str = "visits") -> list[dict[str, Any]]:
    candidates: list[tuple[dict[str, Any], float]] = []
    for child in root.children:
        if child.action is None:
            continue
        average = child.raw_reward / child.visits if child.visits else 0.0
        utility = child.reward / child.visits if child.visits else float("-inf")
        payload = _action_summary(child.action)
        payload["visits"] = child.visits
        payload["averageScore"] = round(average, 3)
        payload["averageUtility"] = round(utility, 6) if child.visits else None
        candidates.append((payload, utility))
    if rank_by == "utility":
        # Paired rounds give every action the same number of visits, so robust
        # child would degrade to input order. The mean bounded utility is the
        # paired estimator; Python's stable sort preserves public action order
        # for an exact tie.
        return [
            payload for payload, _ in sorted(
                candidates,
                key=lambda item: item[1],
                reverse=True,
            )
        ]
    # Independent UCB is ranked by visits first so the displayed order matches
    # how the action is actually chosen. Break visit ties with bounded utility,
    # while still displaying the raw score people recognise.
    return [
        payload for payload, _ in sorted(
            candidates,
            key=lambda item: (item[0].get("visits", 0), item[1]),
            reverse=True,
        )
    ]


def _record_root_reward(root: Node, child: Node, raw_reward: float) -> None:
    """Back-propagate one root-only simulation into its two stored nodes."""
    reward = _search_utility(raw_reward)
    for node in (root, child):
        node.visits += 1
        node.reward += reward
        node.raw_reward += raw_reward


def _child_mean_utility(child: Node | None) -> float | None:
    if child is None or child.visits <= 0:
        return None
    return child.reward / child.visits


def _paired_advantage_stats(proposed: Node | None,
                            baseline: Node | None) -> tuple[int, float, float] | None:
    """Return ``(worlds, mean_delta, lower_bound)`` for paired utilities."""
    if proposed is None or baseline is None:
        return None
    count = min(len(proposed.paired_utilities), len(baseline.paired_utilities))
    if count <= 0:
        return None
    deltas = [
        proposed.paired_utilities[index] - baseline.paired_utilities[index]
        for index in range(count)
    ]
    mean = sum(deltas) / count
    if count < 2:
        standard_error = float("inf")
    else:
        variance = sum((delta - mean) ** 2 for delta in deltas) / (count - 1)
        standard_error = math.sqrt(variance / count)
    lower_bound = mean - MCTS_CONFIDENCE_Z * standard_error
    return count, mean, lower_bound


def _guarded_root_choice(session, root: Node,
                         proposed: Node | None) -> tuple[Node | None, dict[str, Any], str, float | None]:
    """Keep the heuristic root move unless search clears the confidence gate."""
    baseline_action = _heuristic_rollout_action(session)
    baseline_key = _action_key(baseline_action)
    proposed_key = _action_key(proposed.action) if proposed is not None else ()
    baseline_child = next(
        (child for child in root.children if _action_key(child.action) == baseline_key),
        None,
    )

    if proposed is not None and proposed_key == baseline_key:
        return proposed, baseline_action, "agreement", 0.0

    proposed_mean = _child_mean_utility(proposed)
    baseline_mean = _child_mean_utility(baseline_child)
    if proposed_mean is None or baseline_mean is None:
        return baseline_child, baseline_action, "heuristic_guard", None

    advantage = proposed_mean - baseline_mean
    if MCTS_OVERRIDE_GATE == "confidence":
        paired = _paired_advantage_stats(proposed, baseline_child)
        if paired is None:
            return baseline_child, baseline_action, "heuristic_guard", advantage
        worlds, paired_advantage, lower_bound = paired
        if (worlds < MCTS_CONFIDENCE_MIN_WORLDS
                or lower_bound <= MCTS_CONFIDENCE_MIN_EFFECT):
            return baseline_child, baseline_action, "heuristic_guard", paired_advantage
        return proposed, proposed.action, "mcts_override", paired_advantage
    if advantage < MCTS_OVERRIDE_MARGIN:
        return baseline_child, baseline_action, "heuristic_guard", advantage
    return proposed, proposed.action, "mcts_override", advantage


def _paired_root_rounds(session, root: Node, search_rng: random.Random,
                        start: float, budget_ms: int,
                        max_iterations: int | None) -> tuple[int, int] | None:
    """Run complete common-random-number root rounds when they are affordable.

    A round samples one information-set-consistent world, then clones it once
    per public root action.  The branches therefore share hidden-zone contents
    and the initial continuation RNG state, but never persist a sampled child
    state into another decision (so this is not strategy fusion).  Stats are
    committed only after a complete round; a time-expired partial round cannot
    give one action an extra hidden-world sample.

    Returns ``(branch_rollouts, sampled_worlds)`` when paired mode was used,
    otherwise ``None`` so the caller can use independent UCB.  Fixed iteration
    budgets count branch rollouts and intentionally round down to full rounds.
    """
    if ROOT_SAMPLING_MODE != "paired":
        return None
    actions = root.untried_actions[:]
    action_count = len(actions)
    if action_count < 2 or action_count > PAIRED_ROOT_MAX_ACTIONS:
        return None
    if max_iterations is not None and max_iterations < action_count:
        return None
    if max_iterations is None and (perf_counter() - start) * 1000 >= budget_ms:
        return None

    root.children = [Node(action=action, parent=root, actor="bot") for action in actions]
    root.untried_actions = []
    iterations = 0
    worlds = 0
    while True:
        if max_iterations is not None:
            if iterations + action_count > max_iterations:
                break
        elif (perf_counter() - start) * 1000 >= budget_ms:
            break

        try:
            world = session.determinize_for_bot(search_rng)
        except ValueError:
            # A mismatched/custom public inventory cannot be sampled fairly.
            # Fail closed to the public heuristic instead of using the old
            # private-composition fallback or crashing the live bot turn.
            return 0, 0
        opponent_profile = _sample_rollout_opponent_profile(world, search_rng)
        legal = _legal_keys(world)
        if any(_action_key(child.action) not in legal for child in root.children):
            if worlds == 0:
                root.children = []
                root.untried_actions = actions[:]
                return None
            break

        results: list[tuple[Node, float]] = []
        complete = True
        for child in root.children:
            if max_iterations is None and (perf_counter() - start) * 1000 >= budget_ms:
                complete = False
                break
            sim = world.clone()
            apply_action(sim, child.action)
            reward = (_rollout(sim, opponent_profile=opponent_profile)
                      if opponent_profile is not None else _rollout(sim))
            results.append((child, reward))

        if not complete:
            break
        for child, raw_reward in results:
            child.paired_utilities.append(_search_utility(raw_reward))
            _record_root_reward(root, child, raw_reward)
        iterations += action_count
        worlds += 1

    return iterations, worlds


def choose_bot_action(session, budget_ms: int = 60, algorithm: str = "mcts",
                      max_iterations: int | None = None) -> dict[str, Any]:
    start = perf_counter()
    actions = _sorted_actions(legal_actions(session))
    if algorithm == "mcts":
        actions = _root_search_actions(session, actions)
    # Remaining combat vanishes at end of turn. Once at least one legal combat
    # target exists, advancing the phase is therefore strictly dominated; keep
    # MCTS focused on the meaningful target-selection decision instead of
    # occasionally spending its shallow search budget on a pass.
    if session.phase == "combat":
        attacks = [action for action in actions if action["type"] == "attack_target"]
        if attacks:
            actions = _combat_search_actions(session, attacks)
    if not actions:
        return {"type": "advance_phase", "label": "Next Phase", "score": 0.0, "iterations": 0, "elapsedMs": 0}

    # Playing the hand and expending champions are dominated decisions: there is
    # no reason in Hero Realms to hold a card back or leave a champion
    # unexpended. Searching them re-derives a known answer and, worse, injects
    # sampling error. Measured on one play-phase state over 200 rollouts,
    # playing scored -12.6 (sd 9.7) against -31.5 (sd 15.4) for passing - a real
    # 19-point edge, but at ~7 rollouts per child the standard error is ~7, so
    # the search misread it often enough to throw away ~2 cards of tempo a turn.
    # Reserving the budget for buy and combat is both fewer decisions and the
    # only ones where the tradeoff is genuinely situational.
    auto_resolved = session.phase not in SEARCHED_PHASES
    if algorithm != "mcts" or len(actions) == 1 or auto_resolved:
        chosen = _heuristic_rollout_action(session)
        candidates = []
        for action in actions[:3]:
            candidate = _action_summary(action)
            # Keep the UI/result schema consistent with searched choices. A
            # forced heuristic action is the only candidate and is visited
            # once conceptually, even though no UCT loop is required.
            candidate["visits"] = 1
            candidates.append(candidate)
        return {
            **chosen,
            "score": evaluate_state(session.clone()) if hasattr(session, "clone") else 0.0,
            "iterations": 1,
            "elapsedMs": int((perf_counter() - start) * 1000),
            "algorithm": "heuristic",
            "candidates": candidates,
        }

    # This is root-only information-set Monte Carlo. Independent mode samples
    # a fresh hidden world per rollout; paired mode samples one fair world per
    # complete public-action round. Both keep later bot moves inside a greedy
    # rollout rather than persisting sampled descendants, avoiding strategy
    # fusion across incompatible hidden hands.
    root = Node(action=None, untried_actions=actions[:])
    iterations = 0
    best_action = actions[0]
    best_score = float("-inf")
    # Bounded utility has a fixed UCB range. Raw mode retains the historical
    # observed-range normalisation for controlled A/B comparisons.
    reward_lo = 0.0 if MCTS_UTILITY_MODE == "bounded" else float("inf")
    reward_hi = 1.0 if MCTS_UTILITY_MODE == "bounded" else float("-inf")
    # The seed uses public turn state rather than private human cards. Each
    # simulation below gets an independent determinization while repeated
    # searches over the same public position remain reproducible.
    search_rng = random.Random(
        f"mcts:{session.seed}:{session.turn_number}:{session.active_player}:{session.phase}"
    )
    paired_result = _paired_root_rounds(
        session, root, search_rng, start, budget_ms, max_iterations,
    )
    paired = paired_result is not None
    if paired:
        iterations, sampled_worlds = paired_result
    else:
        sampled_worlds = 0
        while (
            iterations < max_iterations
            if max_iterations is not None
            else (perf_counter() - start) * 1000 < budget_ms
        ):
            try:
                sim = session.determinize_for_bot(search_rng)
            except ValueError:
                # See the paired path above: no search estimate is preferable
                # to one derived from live opponent private zones.
                break
            opponent_profile = _sample_rollout_opponent_profile(sim, search_rng)
            node = root
            path = [node]

            if root.untried_actions:
                action = root.untried_actions.pop(0)
                node = Node(action=action, parent=root, actor="bot")
                root.children.append(node)
            else:
                node = max(root.children, key=lambda child: child.uct_score(
                    lo=reward_lo, hi=reward_hi, maximize=True))

            # Root actions are all generated from the bot's public, unchanged
            # state, but keep the check defensive if a caller supplies a custom
            # session implementation.
            if _action_key(node.action) in _legal_keys(sim):
                apply_action(sim, node.action)
                path.append(node)

            raw_reward = (_rollout(sim, opponent_profile=opponent_profile)
                          if opponent_profile is not None else _rollout(sim))
            reward = _search_utility(raw_reward)
            reward_lo = min(reward_lo, reward)
            reward_hi = max(reward_hi, reward)

            for item in path:
                item.visits += 1
                item.reward += reward
                item.raw_reward += raw_reward
            iterations += 1
            sampled_worlds += 1

    candidates = _root_candidates_from_children(
        root, rank_by="utility" if paired else "visits",
    )
    proposed: Node | None = None
    if root.children:
        if paired:
            # Complete paired rounds leave every action equally sampled, so
            # choose the higher mean estimate rather than degenerating to the
            # original public action order on tied visit counts.
            proposed = max(root.children, key=lambda child: (
                child.reward / child.visits if child.visits else float("-inf"),
            ))
        else:
            # Robust-child selection: take the most-visited root child.
            #
            # This used to track the best single rollout reward from any node at
            # any depth, then map it back to a root child by (type, label). But
            # "advance_phase"/"Next Phase" exists in every phase, so a pass from
            # deep inside a rollout routinely matched the root's pass and
            # overrode the search.
            proposed = max(root.children, key=lambda child: (
                child.visits,
                child.reward / child.visits if child.visits else float("-inf"),
            ))
    selected, best_action, selection, utility_advantage = _guarded_root_choice(
        session, root, proposed,
    )
    if selected is not None and selected.visits:
        best_score = selected.raw_reward / selected.visits
    else:
        best_score = 0.0

    return {
        **best_action,
        "score": round(best_score, 3),
        "iterations": iterations,
        "worlds": sampled_worlds,
        "rootSampling": "paired" if paired else "independent",
        "selection": selection,
        "utilityAdvantage": (round(utility_advantage, 6)
                             if utility_advantage is not None else None),
        "elapsedMs": int((perf_counter() - start) * 1000),
        "algorithm": "mcts",
        "candidates": candidates[:5],
    }


def run_bot_turn(session, budget_ms: int = 60, algorithm: str = "mcts") -> dict[str, Any]:
    actions_taken: list[dict[str, Any]] = []
    insight: dict[str, Any] | None = None
    start = perf_counter()

    while session.active_player == "bot" and not session.winner:
        actions = legal_actions(session)
        if not actions:
            session.end_turn()
            break

        # Buy decisions are the main unresolved root search after combat
        # pruning: lethal/face/guard-forced combat normally has one retained
        # action. Give the buy root the full turn slice so balanced opponents'
        # draw/economy cards are not decided from only half the samples.
        decision_budget = budget_ms if session.phase == "buy" else max(20, budget_ms // 2)
        chosen = choose_bot_action(session, decision_budget, algorithm=algorithm)
        insight = chosen
        actions_taken.append(chosen)
        session.last_bot_insight = chosen
        apply_action(session, chosen)

        if chosen["type"] == "advance_phase" and session.active_player != "bot":
            break

        if session.phase == "combat" and session.bot.combat <= 0:
            session.advance_phase()

        if session.phase == "play" and session.active_player != "bot":
            break

        if len(actions_taken) > 20:
            break

    if session.active_player == "bot" and not session.winner:
        session.end_turn()

    total_elapsed = int((perf_counter() - start) * 1000)
    return {
        "algorithm": algorithm,
        "actions": actions_taken,
        "elapsedMs": total_elapsed,
        "finalPhase": session.phase,
        "iterations": sum(item.get("iterations", 0) for item in actions_taken),
        "lastAction": insight,
    }
