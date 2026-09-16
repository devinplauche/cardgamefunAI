"""Regression tests for champion damage and stun handling.

Two rules bugs found by auditing the engine against the printed rules rather
than assuming it was right:

  "Damage to Champions does not carry over between turns."
  "Once stunned, a Champion is placed in its owner's discard pile."

The engine set current_health once in BoardChampion.__init__ and never reset
it, so chip damage accumulated permanently across turns; and every combat
site filtered dead champions off the board with a list comprehension, so the
card left the game entirely instead of returning to its owner's discard.
"""

import unittest

from hero_engine import (
    BoardChampion,
    HRMarket,
    HRPlayer,
    load_hero_cards,
    remove_stunned_champions,
    play_card,
    expend_champion,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")
GUARD = next(c for c in CARDS if c.card_type == "champion" and c.guard > 0 and c.health >= 4)
CHAMP = next(c for c in CARDS if c.card_type == "champion" and c.health >= 3)


class TestStunnedChampionsGoToDiscard(unittest.TestCase):
    def test_session_stun_requires_a_guard_target_when_guards_are_present(self):
        from web.session import create_session

        fire_bomb = next(c for c in CARDS if c.name == "Fire Bomb")
        non_guard_card = next(c for c in CARDS if c.card_type == "champion" and not c.guard)
        non_guard = BoardChampion(non_guard_card)
        guard = BoardChampion(GUARD)
        session = create_session(seed=7)
        session.player.hand = [fire_bomb]
        session.bot.board = [non_guard, guard]

        session.play_card(fire_bomb.id, stun_target_index=0)

        self.assertIn(non_guard, session.bot.board)
        self.assertNotIn(guard, session.bot.board)
        self.assertIn(GUARD, session.bot.discard)

    def test_action_stun_destroys_the_target_champion(self):
        fire_bomb = next(c for c in CARDS if c.name == "Fire Bomb")
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.board.append(BoardChampion(GUARD))
        attacker.hand = [fire_bomb]

        play_card(attacker, fire_bomb, HRMarket(CARDS), opponent=defender)

        self.assertEqual(defender.board, [])
        self.assertIn(GUARD, defender.discard)

    def test_champion_expend_stun_destroys_the_target_champion(self):
        rake = next(c for c in CARDS if c.name == "Rake, Master Assassin")
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        attacker_champion = BoardChampion(rake)
        attacker.board.append(attacker_champion)
        defender.board.append(BoardChampion(GUARD))

        expend_champion(attacker, attacker_champion, defender)

        self.assertEqual(defender.board, [])
        self.assertIn(GUARD, defender.discard)

    def test_a_stun_is_written_to_the_victims_effect_log(self):
        """A stun removes a champion with no combat assigned to it, so
        web/session.py has no action to record and the board change was
        completely silent - playing the UI by hand, a 7-health guard left play
        with the log jumping straight to the attacker's face damage. Noted on
        the victim, which is the player whose board changed and the name
        `_drain_effect_log` prefixes the message with."""
        fire_bomb = next(c for c in CARDS if c.name == "Fire Bomb")
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.board.append(BoardChampion(GUARD))
        attacker.hand = [fire_bomb]

        play_card(attacker, fire_bomb, HRMarket(CARDS), opponent=defender)

        self.assertTrue(
            any(GUARD.name in message and "stunned" in message.lower()
                for message in defender.effect_log),
            f"stun not narrated; defender.effect_log={defender.effect_log}",
        )
        self.assertEqual(attacker.effect_log, [],
                         "the stun belongs to the player who lost the champion")

    def test_stun_narration_is_off_for_simulation_clones(self):
        """`log_effects` is False on clones because play_card runs ~25k times
        per MCTS decision; the new note must respect it like every other."""
        fire_bomb = next(c for c in CARDS if c.name == "Fire Bomb")
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.log_effects = False
        defender.board.append(BoardChampion(GUARD))
        attacker.hand = [fire_bomb]

        play_card(attacker, fire_bomb, HRMarket(CARDS), opponent=defender)

        self.assertEqual(defender.board, [], "the stun itself must still apply")
        self.assertEqual(defender.effect_log, [])

    def test_stunned_champion_lands_in_its_owners_discard(self):
        player = HRPlayer("P")
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 0

        moved = remove_stunned_champions(player)

        self.assertEqual(player.board, [])
        self.assertEqual(player.discard, [GUARD])
        self.assertEqual(moved, [GUARD])

    def test_living_champions_are_untouched(self):
        player = HRPlayer("P")
        alive = BoardChampion(GUARD)
        dead = BoardChampion(CHAMP)
        dead.current_health = 0
        player.board.extend([alive, dead])

        remove_stunned_champions(player)

        self.assertEqual([bc.card for bc in player.board], [GUARD])
        self.assertEqual(player.discard, [CHAMP])

    def test_no_stunned_champions_is_a_noop(self):
        player = HRPlayer("P")
        player.board.append(BoardChampion(GUARD))
        self.assertEqual(remove_stunned_champions(player), [])
        self.assertEqual(player.discard, [])

    def test_a_stunned_champion_can_be_drawn_again(self):
        """The whole point of going to discard rather than out of the game."""
        player = HRPlayer("P")
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 0
        remove_stunned_champions(player)

        player.deck = []
        drawn = player.draw(1)  # forces a reshuffle of the discard pile
        self.assertEqual(drawn, [GUARD])

    def test_combat_through_the_ai_routes_stunned_champions_to_discard(self):
        from hero_ai import attack_weakest

        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        champion = BoardChampion(GUARD)
        defender.board.append(champion)
        attacker.combat = GUARD.health + 5

        attack_weakest(attacker, defender, [champion])

        self.assertEqual(defender.board, [])
        self.assertIn(GUARD, defender.discard)

    def test_combat_through_the_session_routes_stunned_champions_to_discard(self):
        from web.session import create_session

        session = create_session(seed=7)
        champion = BoardChampion(GUARD)
        session.player.board.append(champion)
        session.active_player = "bot"
        session.phase = "combat"
        session.bot.combat = GUARD.health

        session.attack_target_action("champion", str(champion.instance_id))

        self.assertEqual(session.player.board, [])
        self.assertIn(GUARD, session.player.discard)


class TestChampionDamageDoesNotCarryOver(unittest.TestCase):
    def test_damage_resets_at_the_start_of_the_owners_turn(self):
        from web.session import create_session

        session = create_session(seed=4)
        champion = BoardChampion(GUARD)
        session.bot.board.append(champion)
        champion.current_health = 1

        session._start_turn(session.bot)

        self.assertEqual(champion.current_health, GUARD.health)

    def test_damage_persists_within_a_single_turn(self):
        """Only *between* turns does damage clear - a guard chipped twice in
        one turn must still be chipped."""
        from web.session import create_session

        session = create_session(seed=7)
        champion = BoardChampion(GUARD)
        session.player.board.append(champion)
        session.active_player = "bot"
        session.phase = "combat"
        session.bot.combat = 1

        session.attack_target_action("champion", str(champion.instance_id))

        self.assertEqual(champion.current_health, GUARD.health - 1)
        self.assertTrue(champion.alive)

    def test_engine_turn_loop_also_resets_damage(self):
        """hero_engine.HRGame.take_turn drives RL training and the benchmark
        AIs, so it needs the same reset as the web session."""
        from hero_ai import BalancedAI
        from hero_engine import HRGame

        player = HRPlayer("P")
        opponent = HRPlayer("O")
        player.setup_starting_deck()
        opponent.setup_starting_deck()
        player.draw(5)
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 1

        game = HRGame(player, opponent, list(CARDS))
        ai = BalancedAI()
        game.take_turn(player, opponent, ai.buy, ai.play, ai.attack)

        self.assertEqual(champion.current_health, GUARD.health)


if __name__ == "__main__":
    unittest.main()


class TestRetroactivePerChampionBonus(unittest.TestCase):
    """"For each champion you have in play" on a played action (Close Ranks,
    Recruit) tops up retroactively if a champion enters play later the same
    turn - per table experience, not a citable rules text, unlike allies
    (which the base rulebook explicitly confirms). Mirrors the pending_ally
    mechanism: priced at the current count, queued, and topped up to the new
    count whenever a champion joins the board.

    Scoped to played actions only, not champion expend abilities
    (per_other_champion_combat and friends): an expend is a discrete,
    one-time triggered action, not a card sitting in a zone the way an
    ally-bearing action does, so there is nothing for a later champion to
    retroactively add to.
    """

    @staticmethod
    def _inert_champions(count=1):
        """Champions that add nothing but their presence on the board.

        Non-Imperial, so Close Ranks' own Imperial ally line stays quiet, and
        carrying no ally payload of their own - two champions of one faction
        are a faction pair, so an ally-bearing pick would fire its own ally the
        moment the second one lands and swamp the +2 this class measures. The
        original fixture picked Borg and Myros, both Guild, which is exactly
        that collision.
        """
        picked = [c for c in CARDS
                  if c.card_type == "champion"
                  and c.faction != "Imperial"
                  and not c.effects.get("ally_faction")]
        out, seen = [], set()
        for card in picked:
            if card.name not in seen:
                seen.add(card.name)
                out.append(card)
            if len(out) == count:
                return out
        raise AssertionError(f"need {count} inert champions, found {len(out)}")

    @classmethod
    def _non_imperial_champion(cls):
        return cls._inert_champions(1)[0]

    def test_close_ranks_combat_grows_when_a_champion_is_played_after(self):
        from hero_engine import HRMarket, play_card

        close_ranks = next(c for c in CARDS if c.name == "Close Ranks")
        champ = self._non_imperial_champion()
        player = HRPlayer("P")
        player.hand = [close_ranks, champ]
        market = HRMarket(CARDS)

        play_card(player, close_ranks, market, opponent=None)
        self.assertEqual(player.combat, 5, "no champions in play yet")

        play_card(player, champ, market, opponent=None)
        self.assertEqual(player.combat, 7, "should top up by 2 for the new champion")

    def test_recruit_health_grows_when_a_champion_is_played_after(self):
        from hero_engine import HRMarket, play_card

        recruit = next(c for c in CARDS if c.name == "Recruit")
        champ = self._non_imperial_champion()
        player = HRPlayer("P")
        player.hp = 10
        player.hand = [recruit, champ]
        market = HRMarket(CARDS)

        play_card(player, recruit, market, opponent=None)
        hp_after_recruit = player.hp
        play_card(player, champ, market, opponent=None)
        self.assertGreater(player.hp, hp_after_recruit, "should heal further once a champion joins")

    def test_does_not_grow_from_champions_already_in_play(self):
        """Only NEW champions entering later top it up; the count at play
        time is already priced in once."""
        from hero_engine import BoardChampion, HRMarket, play_card

        close_ranks = next(c for c in CARDS if c.name == "Close Ranks")
        champ = self._non_imperial_champion()
        player = HRPlayer("P")
        player.board.append(BoardChampion(champ))
        player.hand = [close_ranks]
        market = HRMarket(CARDS)

        play_card(player, close_ranks, market, opponent=None)
        self.assertEqual(player.combat, 7, "base 5 + 2 for the one already-present champion")

    def test_top_up_only_applies_once_per_new_champion(self):
        from hero_engine import HRMarket, play_card

        def _ally_free_champion(exclude=()):
            # Champions without ally abilities, so the per-champion top-up is
            # measured without ally triggers interfering (champion allies now
            # correctly fire on entering play when a partner is present).
            return next(c for c in CARDS if c.card_type == "champion"
                        and "ally_faction" not in c.effects and c.name not in exclude)

        close_ranks = next(c for c in CARDS if c.name == "Close Ranks")
        champ = _ally_free_champion()
        champ2 = _ally_free_champion(exclude=(champ.name,))
        player = HRPlayer("P")
        player.hand = [close_ranks, champ, champ2]
        market = HRMarket(CARDS)

        play_card(player, close_ranks, market, opponent=None)
        play_card(player, champ, market, opponent=None)
        after_first = player.combat
        play_card(player, champ2, market, opponent=None)
        self.assertEqual(player.combat, after_first + 2, "second champion should also top up by 2")

    def test_pending_per_champion_does_not_leak_across_turns(self):
        from hero_engine import HRMarket, play_card
        from web.session import create_session

        close_ranks = next(c for c in CARDS if c.name == "Close Ranks")
        session = create_session(seed=5)
        session.bot.hand = [close_ranks]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(close_ranks.id)
        self.assertTrue(session.bot.pending_per_champion)

        session._start_turn(session.bot)
        self.assertEqual(session.bot.pending_per_champion, [])

    def test_pending_per_champion_survives_a_clone(self):
        from web.session import create_session

        close_ranks = next(c for c in CARDS if c.name == "Close Ranks")
        session = create_session(seed=5)
        session.bot.hand = [close_ranks]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(close_ranks.id)

        clone = session.clone()
        self.assertEqual(len(clone.bot.pending_per_champion), 1)
        clone.bot.pending_per_champion.clear()
        self.assertTrue(session.bot.pending_per_champion, "clone must not share the list")

    def test_champion_expend_per_other_effects_are_not_retroactive(self):
        """Scoping check: expend abilities resolve once, at time of use, not
        queued for later top-up."""
        from hero_engine import BoardChampion, expend_champion

        master_weyan = next(c for c in CARDS if c.name == "Master Weyan")
        other_champ = self._non_imperial_champion()
        player = HRPlayer("P")
        bc = BoardChampion(master_weyan)
        player.board.append(bc)

        expend_champion(player, bc, opponent=None)
        combat_after_expend = player.combat
        self.assertEqual(player.pending_per_champion, [],
                         "expend abilities must not be queued for retroactive top-up")

        player.board.append(BoardChampion(other_champ))
        self.assertEqual(player.combat, combat_after_expend,
                         "a later champion must not retroactively boost an already-resolved expend")


class TestAutoExpend(unittest.TestCase):
    """Champions whose expend only adds gold/combat expend themselves.

    No choices, costs, or targets - the tap is pure friction. Guards are
    excluded: expending a guard drops its block, a real decision.
    """

    def _play(self, name):
        from hero_engine import HRPlayer, play_card
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        card = next(c for c in CARDS if c.name == name)
        market = HRMarket(CARDS)
        player.hand = [card]
        play_card(player, card, market, opponent=opponent)
        return player, player.board[0]

    def test_simple_combat_champion_expends_itself_on_play(self):
        player, bc = self._play("Rayla, Endweaver")  # expend: +3 combat
        self.assertTrue(bc.exhausted, "should be expended on entering play")
        self.assertEqual(player.combat, 3)

    def test_simple_gold_champion_expends_itself_on_play(self):
        player, bc = self._play("Rasmus, the Smuggler")  # expend: +2 gold
        self.assertTrue(bc.exhausted)
        self.assertEqual(player.gold, 2)

    def test_guard_does_not_auto_expend(self):
        # Orc Grunt's expend is simple (+2 combat) but it is a guard:
        # expending drops its block, so the player decides.
        player, bc = self._play("Orc Grunt")
        self.assertFalse(bc.exhausted, "guards stay manual")
        self.assertEqual(player.combat, 0)

    def test_or_choice_champion_does_not_auto_expend(self):
        player, bc = self._play("Cult Priest")  # expend: 1 gold OR 1 combat
        self.assertFalse(bc.exhausted)
        self.assertEqual(player.combat, 0)
        self.assertEqual(player.gold, 0)

    def test_champion_with_side_effects_does_not_auto_expend(self):
        player, bc = self._play("Rake, Master Assassin")  # expend: 4 combat + stun
        self.assertFalse(bc.exhausted)

    def test_ally_trigger_still_offered_after_auto_expend(self):
        # Auto-expend must not swallow the manual ally trigger: Orc Grunt is
        # a guard (no auto-expend), so use a faction pair where the simple
        # champion's ally still gets offered.
        from hero_engine import HRPlayer, play_card
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        market = HRMarket(CARDS)
        rayla = next(c for c in CARDS if c.name == "Rayla, Endweaver")  # Necros
        partner = next(c for c in CARDS
                       if c.card_type == "champion" and c.faction == "Necros"
                       and c.name != "Rayla, Endweaver")
        player.hand = [partner, rayla]
        play_card(player, partner, market, opponent=opponent)
        play_card(player, rayla, market, opponent=opponent)
        self.assertIn(rayla, player.available_ally_triggers,
                      "ally must still be offered after auto-expend")

    def test_simple_champion_auto_expends_at_turn_start(self):
        from web.session import create_session
        from hero_engine import BoardChampion
        session = create_session(seed=11)
        rayla = next(c for c in CARDS if c.name == "Rayla, Endweaver")
        bc = BoardChampion(rayla)
        session.player.board = [bc]
        session._start_turn(session.player)
        self.assertTrue(bc.exhausted, "should expend itself at turn start")
        self.assertEqual(session.player.combat, 3)
