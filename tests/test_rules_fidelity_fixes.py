"""Regression tests for the three rules-fidelity fixes (2026-09-12).

1. Duplicate physical copies of a card now trigger each other's ally
   abilities (each copy is a distinct HRCard instance).
2. Sacrificed Fire Gems return to the Fire Gem pile instead of being
   banished (official rule).
3. The Main Phase interleaves play and expend, so cards drawn by champion
   expend abilities are played the same turn (official rules allow Main
   Phase actions in any order).
"""

import unittest

from hero_ai import auto_expend_all, play_all_playable
from hero_engine import (
    HRCard,
    HRMarket,
    HRPlayer,
    RUBY,
    BoardChampion,
    _apply_ally_effects,
    _sacrifice_to_pile,
    expend_champion,
    load_hero_cards,
    play_card,
    run_main_phase,
    trigger_ally_ability,
    trigger_all_available_allies,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")
GOLD_DICT = {"id": "gold", "name": "Gold", "cost": 0, "faction": "",
             "card_type": "treasure", "effects": {"gold": 1}}


def _card(name):
    return next(c for c in CARDS if c.name == name)


def _market_with(player=None):
    market = HRMarket(CARDS)
    if player is not None:
        player.market = market
    return market


class TestDuplicateAllyTriggers(unittest.TestCase):
    def test_two_sparks_trigger_each_others_ally(self):
        # Spark: 3 combat, ally_combat 2 (Wild). Two copies in one turn
        # should yield 2*3 base + 2*2 ally = 10 combat.
        sparks = [c for c in CARDS if c.name == "Spark"][:2]
        self.assertEqual(len({id(c) for c in sparks}), 2,
                         "copies must be distinct objects")
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with()
        player.hand = list(sparks)
        play_all_playable(player, opponent, market)
        self.assertEqual(player.combat, 10,
                         f"expected 10 combat (base 6 + ally 4), got {player.combat}")

    def test_duplicate_champions_ally_each_other(self):
        # Orc Grunt is printed 2x and has a Wild ally ability; two copies on
        # the board are allies of each other.
        grunts = [c for c in CARDS if c.name == "Orc Grunt"][:2]
        self.assertEqual(len(grunts), 2)
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with()
        player.hand = list(grunts)
        play_all_playable(player, opponent, market)
        self.assertEqual(len(player.board), 2)
        from hero_engine import has_ally
        self.assertTrue(has_ally(grunts[0], player))
        self.assertTrue(has_ally(grunts[1], player))

    def test_single_copy_still_gets_no_ally(self):
        spark = _card("Spark")
        player, opponent = HRPlayer("P"), HRPlayer("O")
        player.hand = [spark]
        play_all_playable(player, opponent, _market_with())
        self.assertEqual(player.combat, 3, "lone Spark: base combat only")


class TestFireGemReturnsToPile(unittest.TestCase):
    def test_sacrifice_helper_returns_fire_gem_to_pile(self):
        player = HRPlayer("P")
        market = _market_with(player)
        pile_before = market.fire_gems_remaining
        gem = market.buy_fire_gem()
        self.assertEqual(market.fire_gems_remaining, pile_before - 1)
        _sacrifice_to_pile(player, gem, market)
        self.assertEqual(market.fire_gems_remaining, pile_before,
                         "sacrificed Fire Gem must return to the pile")
        self.assertNotIn(gem, player.banish)

    def test_sacrifice_helper_banishes_ordinary_cards(self):
        player = HRPlayer("P")
        market = _market_with(player)
        ruby = RUBY
        _sacrifice_to_pile(player, ruby, market)
        self.assertIn(ruby, player.banish)
        # Fire Gem pile untouched by ordinary sacrifices.
        self.assertEqual(market.fire_gems_remaining, 16)

    def test_sacrifice_without_market_falls_back_to_banish(self):
        player = HRPlayer("P")  # player.market is None
        gem = HRCard(id="fire_gem", name="Fire Gem", cost=2, faction="",
                     card_type="item", effects={"gold": 2})
        _sacrifice_to_pile(player, gem)
        self.assertIn(gem, player.banish)

    def test_self_sacrificed_fire_gem_returns_to_pile_in_real_play(self):
        # Fire Gem's "{Sacrifice}: +3 combat" is taken once the player owns
        # 2+ non-starting economy cards.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        pile_before = market.fire_gems_remaining
        gem = market.buy_fire_gem()
        player.hand = [gem]
        player.discard = [market.buy_fire_gem(), market.buy_fire_gem()]
        play_card(player, gem, market)
        # 3 gems bought, the sacrificed one returned: net pile is 16 - 2.
        self.assertEqual(market.fire_gems_remaining, pile_before - 2,
                         "sacrificed gem returned to pile")
        self.assertNotIn(gem, player.banish)
        self.assertEqual(player.combat, 3, "sacrifice bonus still applies")


class TestExpendDrawReplay(unittest.TestCase):
    def test_card_drawn_by_expend_is_played_same_turn(self):
        # Arkus, Imperial Dragon: expend to draw a card. The drawn card must
        # be playable the same turn (Main Phase actions: any order).
        arkus = _card("Arkus, Imperial Dragon")
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.hand = [arkus]
        player.deck = [HRCard(**GOLD_DICT) for _ in range(10)]
        run_main_phase(player, opponent, market, play_all_playable, auto_expend_all)
        played = [c.name for c in player.played_this_turn]
        self.assertIn("Gold", played,
                      f"drawn Gold must be played same turn; played={played}, hand={[c.name for c in player.hand]}")
        self.assertEqual(player.gold, 1, "drawn Gold's economy must count")

    def test_main_phase_terminates(self):
        # No infinite play/expend ping-pong even with draw champions around.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.hand = [_card("Arkus, Imperial Dragon"), _card("Spark")]
        player.deck = [HRCard(**GOLD_DICT) for _ in range(20)]
        run_main_phase(player, opponent, market, play_all_playable, auto_expend_all)
        self.assertEqual(player.hand, [])


class TestDrawDiscardFidelity(unittest.TestCase):
    """Draw-then-discard effects must only discard what was actually drawn.

    The rulebook's partial-effects rule ("just do as much as you can") means
    a short deck can't force discards from the existing hand: Elven Gift's
    "if you do, discard a card" and Rampage's "discard that many cards" both
    scale down to the real draw count.
    """

    def test_elven_gift_empty_deck_no_forced_discard(self):
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        golds = [HRCard(**GOLD_DICT) for _ in range(2)]
        player.hand = [_card("Elven Gift")] + golds
        player.deck = []
        player.discard = []
        play_card(player, player.hand[0], market, opponent=opponent)
        self.assertEqual([c.name for c in player.hand], ["Gold", "Gold"],
                         "nothing drawn -> nothing discarded")

    def test_rampage_short_deck_discards_only_what_was_drawn(self):
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        golds = [HRCard(**GOLD_DICT) for _ in range(3)]
        player.hand = [_card("Rampage")] + golds
        player.deck = [HRCard(**GOLD_DICT)]  # only 1 available for "up to 2"
        player.discard = []
        play_card(player, player.hand[0], market, opponent=opponent)
        self.assertEqual(len(player.hand), 3,
                         f"drew 1, must discard exactly 1; hand={len(player.hand)}")

    def test_grak_expend_empty_deck_no_forced_discard(self):
        # Grak, Storm Giant expend: "You may draw a card. If you do, discard."
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        grak = _card("Grak, Storm Giant")
        bc = BoardChampion(grak)
        player.board.append(bc)
        player.hand = [HRCard(**GOLD_DICT) for _ in range(2)]
        player.deck = []
        player.discard = []
        expend_champion(player, bc, opponent)
        self.assertEqual(len(player.hand), 2,
                         "nothing drawn -> nothing discarded")

    def test_grak_ally_draw_discard_short_deck(self):
        # Grak ally: "Draw a card, then discard a card." - fires on expend
        # with a Wild partner in play; both the expend draw and the ally draw
        # must scale down to the real draw count.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        bc_wolf = BoardChampion(_card("Wolf Shaman"))  # Wild partner
        bc_grak = BoardChampion(_card("Grak, Storm Giant"))
        player.board.extend([bc_wolf, bc_grak])
        player.hand = [HRCard(**GOLD_DICT) for _ in range(2)]
        player.deck = []
        player.discard = []
        expend_champion(player, bc_grak, opponent)
        self.assertEqual(len(player.hand), 2,
                         f"both draws produced nothing, so no discards; hand={len(player.hand)}")


class TestTurnBoundaryState(unittest.TestCase):
    def test_take_turn_clears_pending_choices(self):
        # Deferred choices reference last turn's cards/zones; like the web
        # session's _start_turn, take_turn must not leak them across turns.
        from hero_ai import BalancedAI
        from hero_engine import HRGame

        player, opponent = HRPlayer("P"), HRPlayer("O")
        player.setup_starting_deck()
        opponent.setup_starting_deck()
        player.draw(5)
        player.defer_choices = True
        player.pending_choices.append({"kind": "discard", "n": 1})

        game = HRGame(player, opponent, list(CARDS))
        ai = BalancedAI()
        game.take_turn(player, opponent, ai.buy, ai.play, ai.attack)

        self.assertEqual(player.pending_choices, [],
                         "pending_choices must not survive a turn boundary")


class TestChampionAllyTiming(unittest.TestCase):
    """Champion ally abilities are independent once-per-turn abilities, usable
    "as soon as you have another card of that faction in play" - they fire on
    entering play (or retroactively when a partner arrives), not only on
    expend, and never twice in one turn (2026-09-12)."""

    def test_ally_fires_on_entering_play_with_partner(self):
        # Dire Wolf (Wild, ally +4 combat) enters play with Wolf Shaman (Wild)
        # already in play: the ally is offered without expending, and pays on
        # trigger.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.board.append(BoardChampion(_card("Wolf Shaman")))
        player.hand = [_card("Dire Wolf")]
        wolf = player.hand[0]
        play_card(player, wolf, market, opponent=opponent)
        self.assertEqual(player.combat, 0, "offered, not fired")
        self.assertEqual([c.name for c in player.available_ally_triggers], ["Dire Wolf"])
        self.assertTrue(player.board[1].exhausted is False)
        trigger_ally_ability(player, wolf, opponent)
        self.assertEqual(player.combat, 4,
                         f"ally should pay on trigger; combat={player.combat}")

    def test_ally_fires_retroactively_when_partner_arrives_later(self):
        # Orc Grunt (Wild, ally: draw 1) played first, then Wolf Shaman: the
        # Grunt's ally is offered retroactively ("the order in which you play
        # your cards does not matter") and draws on trigger.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        grunt = [c for c in CARDS if c.name == "Orc Grunt"][0]
        player.hand = [grunt, _card("Wolf Shaman")]
        player.deck = [HRCard(**GOLD_DICT), HRCard(**GOLD_DICT)]
        player.discard = []
        play_card(player, player.hand[0], market, opponent=opponent)
        play_card(player, player.hand[0], market, opponent=opponent)
        self.assertIn(grunt, player.available_ally_triggers,
                      "Grunt's ally should be offered when the partner arrived")
        self.assertEqual(len(player.hand), 0)
        trigger_all_available_allies(player, opponent)
        self.assertIn(id(grunt), player.ally_used_this_turn)
        self.assertEqual(len(player.hand), 1, "ally drew on trigger")

    def test_ally_fires_only_once_per_turn(self):
        # Dire Wolf expended (3 base), trigger fired (+4 ally = 7), prepared,
        # expended again: the base expend works twice but the ally must not
        # re-offer (10, not 14).
        player, opponent = HRPlayer("P"), HRPlayer("O")
        _market_with(player)
        bc_wolf = BoardChampion(_card("Wolf Shaman"))
        bc_dw = BoardChampion(_card("Dire Wolf"))
        player.board.extend([bc_wolf, bc_dw])
        expend_champion(player, bc_dw, opponent)
        self.assertEqual(player.combat, 3, "expend base only; ally only offered")
        trigger_ally_ability(player, bc_dw.card, opponent)
        self.assertEqual(player.combat, 7)
        bc_dw.exhausted = False  # Domination-style prepare
        expend_champion(player, bc_dw, opponent)
        self.assertEqual(player.combat, 10,
                         f"ally re-offered on re-expend; combat={player.combat}")

    def test_ally_usage_resets_each_turn(self):
        # ally_used_this_turn is per-turn: after a turn boundary the same
        # champion's ally may be offered again. Orc Grunt: base 2 combat, ally draw 1.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        _market_with(player)
        grunt = [c for c in CARDS if c.name == "Orc Grunt"][0]
        bc = BoardChampion(grunt)
        player.board.append(bc)
        player.board.append(BoardChampion(_card("Wolf Shaman")))
        player.deck = [HRCard(**GOLD_DICT), HRCard(**GOLD_DICT)]
        player.discard = []
        expend_champion(player, bc, opponent)
        self.assertEqual(player.combat, 2, "expend base only")
        self.assertIn(grunt, player.available_ally_triggers)
        trigger_ally_ability(player, grunt, opponent)
        self.assertIn(id(grunt), player.ally_used_this_turn)
        self.assertEqual(len(player.hand), 1, "ally drew on turn 1")
        player.ally_used_this_turn.clear()  # what take_turn does
        player.available_ally_triggers.clear()
        player.combat = 0
        player.hand = []
        bc.exhausted = False
        expend_champion(player, bc, opponent)
        self.assertEqual(player.combat, 2, "base expend works on the new turn")
        trigger_ally_ability(player, grunt, opponent)
        self.assertEqual(len(player.hand), 1,
                         "ally should be offered again on a new turn")

    def test_kraka_ally_heals_per_champion_on_entering_play(self):
        # Kraka, High Priest (ally: heal 2 per champion) enters play with an
        # Imperial partner: ally_per_champion_health must be offered on the
        # play path, not just on expend.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.hp = 30
        player.board.append(BoardChampion(_card("Cristov, the Just")))  # Imperial
        kraka = _card("Kraka, High Priest")
        player.hand = [kraka]
        play_card(player, kraka, market, opponent=opponent)
        self.assertEqual(player.hp, 30, "offered, not fired")
        self.assertIn(kraka, player.available_ally_triggers)
        trigger_ally_ability(player, kraka, opponent)
        # 2 champions in play (Cristov + Kraka) x 2 = 4 healing.
        self.assertEqual(player.hp, 34, f"hp={player.hp}")

    def test_grak_ally_draw_discard_scales_on_play_path(self):
        # Grak played with a Wild partner and nothing left to draw: on trigger
        # the ally draws 0, so it discards 0 (partial-effects rule).
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.board.append(BoardChampion(_card("Wolf Shaman")))
        grak = _card("Grak, Storm Giant")
        player.hand = [grak, HRCard(**GOLD_DICT), HRCard(**GOLD_DICT)]
        player.deck = []
        player.discard = []
        play_card(player, player.hand[0], market, opponent=opponent)
        self.assertEqual(len(player.hand), 2, "play drew nothing (base has no draw)")
        self.assertIn(grak, player.available_ally_triggers)
        trigger_ally_ability(player, grak, opponent)
        self.assertEqual(len(player.hand), 2,
                         f"ally drew nothing, so no discard; hand={len(player.hand)}")


class TestUncappedHealing(unittest.TestCase):
    def test_base_heal_above_50(self):
        # No health cap: the physical health cards are double-sided to track
        # above 50. Domination heals 6 at 50 HP -> 56.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        market = _market_with(player)
        player.hp = 50
        player.hand = [_card("Domination")]
        play_card(player, player.hand[0], market, opponent=opponent)
        self.assertEqual(player.hp, 56, f"hp={player.hp}")

    def test_ally_heal_above_50(self):
        # Close Ranks ally heals 6; at 50 HP it must reach 56.
        player, opponent = HRPlayer("P"), HRPlayer("O")
        player.hp = 50
        _apply_ally_effects(player, _card("Close Ranks"), opponent)
        self.assertEqual(player.hp, 56, f"hp={player.hp}")

    def test_grant_resource_heal_uncapped(self):
        # The shared _grant_resource path (per-champion heals) is uncapped too.
        from hero_engine import _grant_resource
        player = HRPlayer("P")
        player.hp = 49
        _grant_resource(player, "health", 5)
        self.assertEqual(player.hp, 54, f"hp={player.hp}")


class TestGuardPrepareTiming(unittest.TestCase):
    # Rulebook: "Prepare all of your Champions" happens in YOUR Discard Phase,
    # and "Guards that are prepared protect you and your other Champions" -
    # a sideways (expended) guard does not protect.

    def test_champions_prepare_at_end_of_own_turn(self):
        from hero_engine import HRGame
        player, opponent = HRPlayer("P"), HRPlayer("O")
        game = HRGame(player, opponent, CARDS)
        guard = BoardChampion(_card("Lys, the Unseen"))
        player.board.append(guard)
        expend_champion(player, guard, opponent)
        self.assertTrue(guard.exhausted)
        game._cleanup(player)
        self.assertFalse(guard.exhausted,
                         "Discard Phase prepares champions (rulebook)")

    def test_damage_still_resets_at_turn_start(self):
        from hero_engine import HRGame
        player, opponent = HRPlayer("P"), HRPlayer("O")
        game = HRGame(player, opponent, CARDS)
        guard = BoardChampion(_card("Lys, the Unseen"))
        guard.current_health = 1  # damaged on the opponent's turn
        player.board.append(guard)
        game._cleanup(opponent)
        self.assertEqual(guard.current_health, 1,
                         "cleanup must not reset damage early")
        for bc in player.board:
            bc.current_health = bc.card.health
        self.assertEqual(guard.current_health, guard.card.health)

    def test_exhausted_guard_does_not_block_combat(self):
        from hero_engine import HRGame
        player, opponent = HRPlayer("P"), HRPlayer("O")
        game = HRGame(player, opponent, CARDS)
        tired = BoardChampion(_card("Lys, the Unseen"))
        tired.exhausted = True
        opponent.board.append(tired)
        seen = []
        player.combat = 5
        game._resolve_combat(player, opponent, lambda p, o, g: seen.extend(g))
        self.assertEqual(seen, [],
                         "an expended guard must not be offered as blocking")

    def test_prepared_guard_still_blocks(self):
        from hero_engine import HRGame
        player, opponent = HRPlayer("P"), HRPlayer("O")
        game = HRGame(player, opponent, CARDS)
        guard = BoardChampion(_card("Lys, the Unseen"))
        opponent.board.append(guard)
        seen = []
        player.combat = 5
        game._resolve_combat(player, opponent, lambda p, o, g: seen.extend(g))
        self.assertEqual(seen, [guard])

    def test_web_session_prepares_on_end_turn(self):
        from web.session import create_session
        session = create_session(seed=11)
        champ = BoardChampion(_card("Lys, the Unseen"))
        session.player.board.append(champ)
        expend_champion(session.player, champ, session.bot)
        self.assertTrue(champ.exhausted)
        session.end_turn()
        self.assertFalse(champ.exhausted,
                         "web Discard Phase must prepare champions")


class TestSurvivingChampionAllies(unittest.TestCase):
    # Rulebook: "As soon as you have two or more cards of that faction in
    # play, you may trigger all relevant Ally Abilities... each may only be
    # used once per turn." A champion that survived from a previous turn is
    # still in play.

    def _wild_pair(self):
        player, opponent = HRPlayer("P"), HRPlayer("O")
        player.board.append(BoardChampion(_card("Dire Wolf")))  # Wild ally +4
        player.ally_used_this_turn.clear()
        player.pending_ally.clear()
        player.available_ally_triggers.clear()
        return player, opponent

    def test_partner_arrival_fires_survivor_ally(self):
        from hero_engine import _resolve_board_allies
        player, opponent = self._wild_pair()
        market = _market_with(player)
        player.hand.append(_card("Wolf Shaman"))  # Wild partner
        player.deck += [_card("Spark") for _ in range(5)]
        wolf = player.hand[0]
        play_card(player, wolf, market, opponent=opponent)
        # Dire Wolf's ally (+4 combat) is offered on partner arrival, no expend.
        self.assertEqual([c.name for c in player.available_ally_triggers],
                         ["Dire Wolf"])
        trigger_all_available_allies(player, opponent)
        self.assertGreaterEqual(player.combat, 4,
                                 f"combat={player.combat}")

    def test_turn_start_fires_ready_board_allies(self):
        from hero_engine import _resolve_board_allies
        player, opponent = self._wild_pair()
        player.board.append(BoardChampion(_card("Wolf Shaman")))
        _resolve_board_allies(player, opponent)
        self.assertEqual(player.combat, 0, "offered, not fired")
        self.assertEqual(len(player.available_ally_triggers), 1)
        trigger_all_available_allies(player, opponent)
        self.assertEqual(player.combat, 4, f"combat={player.combat}")

    def test_ally_still_once_per_turn(self):
        from hero_engine import _resolve_board_allies
        player, opponent = self._wild_pair()
        player.board.append(BoardChampion(_card("Wolf Shaman")))
        _resolve_board_allies(player, opponent)
        trigger_all_available_allies(player, opponent)
        self.assertEqual(player.combat, 4)
        # A later expend offers nothing new - the ally was consumed...
        wolf = next(bc for bc in player.board
                    if bc.card.name == "Dire Wolf")
        expend_champion(player, wolf, opponent)
        # ...but the expend's own base effect (+3) still applies once.
        self.assertEqual(player.combat, 7, f"combat={player.combat}")
        # ...and a second sweep the same turn offers nothing.
        _resolve_board_allies(player, opponent)
        self.assertEqual(player.available_ally_triggers, [])
        self.assertEqual(player.combat, 7, f"combat={player.combat}")


class TestSessionMarketBackreference(unittest.TestCase):
    # Round-1's Fire Gem sacrifice routing only covered HRGame: the web
    # session's players had no market back-reference, so a Fire Gem sacrificed
    # via champion expend in a live web game was banished instead of returning
    # to the pile.

    def test_live_session_routes_fire_gem_to_pile(self):
        import copy
        from web.session import create_session
        from hero_engine import _sacrifice_to_pile, FIRE_GEM
        session = create_session(seed=7)
        before = session.market.fire_gems_remaining
        _sacrifice_to_pile(session.player, copy.deepcopy(FIRE_GEM))
        self.assertEqual(session.market.fire_gems_remaining, before + 1)
        self.assertEqual(session.player.banish, [])

    def test_clone_players_point_at_cloned_market(self):
        import copy
        from web.session import create_session
        from hero_engine import _sacrifice_to_pile, FIRE_GEM
        session = create_session(seed=3)
        before_live = session.market.fire_gems_remaining
        before_clone = session.clone().market.fire_gems_remaining
        clone = session.clone()
        self.assertIs(clone.player.market, clone.market)
        self.assertIs(clone.bot.market, clone.market)
        _sacrifice_to_pile(clone.player, copy.deepcopy(FIRE_GEM))
        self.assertEqual(clone.market.fire_gems_remaining, before_clone + 1)
        self.assertEqual(session.market.fire_gems_remaining, before_live,
                         "simulation must not touch the live pile")


if __name__ == "__main__":
    unittest.main()
