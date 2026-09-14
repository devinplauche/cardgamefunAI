"""Champions are addressed by instance_id, never by card id.

Found by a human playing the web UI, not by any benchmark - and it could not
have been found by one. Every benchmark and A/B in this repo drives the engine
directly through `session.legal_actions()` / `apply_action()`, which pass the
engine's own action dicts straight back in. The web UI is the only consumer
that *constructs* an action from a rendered view, so it is the only place a
wrong identifier can be introduced, and 2800+ benchmark games never touched
that path.

The bug: `_champion_view` emits `instanceId`, `ChampionView` in types.ts did
not declare it, and App.tsx therefore fell back to `champion.id` - the *card*
id. `expend_champion_action` and `attack_target_action` both match on
`str(instance_id)`, so every lookup failed:

    Expend Lys      -> "Champion not found"
    Attack a guard  -> "Champion not found or not a legal target"

One missing field broke champion expend AND all champion-targeted combat,
which between them make the game unplayable past the first champion.

These tests pin the engine contract. The frontend fix is a matching
`instanceId` on ChampionView plus passing it at the two call sites.
"""
import unittest

from hero_engine import BoardChampion, load_hero_cards
from web.session import create_session

CARDS = {card.name: card for card in load_hero_cards("data/hero_realms_cards.json")}


class TestChampionAddressing(unittest.TestCase):
    def _session_with_champion(self, name="Lys, the Unseen", phase="champion"):
        session = create_session(seed=7)
        session.player.board.append(BoardChampion(CARDS[name]))
        session.active_player = "player"
        session.phase = phase
        return session, session.player.board[0]

    def test_expend_rejects_the_card_id(self):
        """The exact failure a human hit in the UI."""
        session, champion = self._session_with_champion()
        with self.assertRaisesRegex(ValueError, "Champion not found"):
            session.expend_champion_action(champion.card.id)

    def test_expend_accepts_the_instance_id(self):
        session, champion = self._session_with_champion()
        session.expend_champion_action(str(champion.instance_id))
        self.assertTrue(session.player.board[0].exhausted)

    def test_attack_rejects_the_card_id(self):
        session, _ = self._session_with_champion(phase="combat")
        session.player.board.clear()
        session.bot.board.append(BoardChampion(CARDS["Lys, the Unseen"]))
        session.player.combat = 10
        target = session.bot.board[0]
        with self.assertRaisesRegex(ValueError, "Champion not found"):
            session.attack_target_action("champion", target.card.id)

    def test_attack_accepts_the_instance_id(self):
        session, _ = self._session_with_champion(phase="combat")
        session.player.board.clear()
        session.bot.board.append(BoardChampion(CARDS["Lys, the Unseen"]))
        session.player.combat = 10
        target = session.bot.board[0]
        session.attack_target_action("champion", str(target.instance_id))
        self.assertEqual(session.bot.board, [], "a stunned champion leaves the board")

    def test_legal_actions_advertise_the_instance_id(self):
        """Whatever legal_actions() puts in championId is what a client must
        send back - this is the contract the UI has to honour."""
        session, champion = self._session_with_champion()
        expends = [a for a in session.legal_actions() if a["type"] == "expend_champion"]
        self.assertTrue(expends)
        for action in expends:
            self.assertEqual(action["championId"], str(champion.instance_id))
            self.assertNotEqual(action["championId"], champion.card.id)

    def test_two_copies_of_one_card_are_separately_addressable(self):
        """Why instance_id exists at all: a card printed in multiple copies can
        appear twice on one board, and card id cannot tell them apart."""
        session = create_session(seed=7)
        card = CARDS["Lys, the Unseen"]
        session.player.board.extend([BoardChampion(card), BoardChampion(card)])
        session.active_player = "player"
        session.phase = "champion"
        first, second = session.player.board
        self.assertEqual(first.card.id, second.card.id)
        self.assertNotEqual(first.instance_id, second.instance_id)

        session.expend_champion_action(str(first.instance_id))
        self.assertTrue(first.exhausted)
        self.assertFalse(second.exhausted, "expending one copy must not exhaust the other")


class TestFireGemIsReachable(unittest.TestCase):
    """Fire Gem is marketIndex 5 but is not part of market.row, which holds only
    the 5 visible slots. The UI rendered tiles from market.row alone, so its
    `index === 5 ? 'Buy Fire Gem'` branch was unreachable and a human could
    never buy one - while the bot buys ~2.9 per game via the engine API."""

    def test_market_row_has_five_slots_and_excludes_fire_gem(self):
        session = create_session(seed=7)
        self.assertEqual(len(session.market.row), 5)
        self.assertNotIn("fire_gem", [c.id for c in session.market.row if c])

    def test_index_five_buys_a_fire_gem(self):
        session = create_session(seed=7)
        session.active_player = "player"
        session.phase = "buy"
        session.player.gold = 2
        before = session.market.fire_gems_remaining
        session.buy_card_action(5)
        self.assertEqual(session.market.fire_gems_remaining, before - 1)
        self.assertIn("fire_gem", [c.id for c in session.player.discard])

    def test_fire_gem_is_offered_in_legal_actions_at_two_gold(self):
        session = create_session(seed=7)
        session.active_player = "player"
        session.phase = "buy"
        session.player.gold = 2
        indices = [int(a["marketIndex"]) for a in session.legal_actions()
                   if a["type"] == "buy_card"]
        self.assertIn(5, indices)



class TestMainPhaseRestoresAcquireToHand(unittest.TestCase):
    """The printed turn structure, and the bug it used to cause.

    Rulebook: "Any time during your Main Phase, you may perform any of the
    following, in any order, as many times as you are able: play a card from
    your hand ... use Gold to acquire new cards from the Market ... use Combat
    to attack". The engine used to enforce play -> champion -> buy -> combat as
    a one-way ratchet, so a card Deception's Guild ally put into hand during the
    buy phase could never be played and was discarded unused - the ally was a
    no-op. This is the regression test for the fix.
    """

    def test_a_card_acquired_to_hand_can_be_played_the_same_turn(self):
        from hero_engine import load_hero_cards

        cards = {c.name: c for c in load_hero_cards("data/hero_realms_cards.json")}
        session = create_session(seed=7)
        session.active_player = "player"
        session.player.hand = [cards["Deception"], cards["Profit"]]
        session.player.played_this_turn = []

        session.play_card(cards["Profit"].id)      # Guild card in play -> ally live
        session.play_card(cards["Deception"].id)
        self.assertTrue(session.player.next_buy_to_hand, "Guild ally should arm to_hand")

        session.player.gold = 9
        index = next(i for i, c in enumerate(session.market.row_cards())
                     if c and c.card_type == "champion")
        acquired = session.market.row_cards()[index].name
        session.buy_card_action(index)
        self.assertIn(acquired, [c.name for c in session.player.hand])

        # The whole point: it is playable right now, mid-turn, after buying.
        playable = {a["label"] for a in session.legal_actions()
                    if a["type"] == "play_card"}
        self.assertIn(acquired, playable)

        session.play_card(next(c.id for c in session.player.hand if c.name == acquired))
        self.assertIn(acquired, [bc.card.name for bc in session.player.board])
        self.assertFalse(session.player.board[-1].exhausted,
                         "and it arrives ready, so it can still be expended")

    def test_every_category_is_legal_at_once(self):
        session = create_session(seed=7)
        session.active_player = "player"
        session.player.gold = 9
        session.player.combat = 5
        types = {a["type"] for a in session.legal_actions()}
        self.assertEqual(types,
                         {"play_card", "buy_card", "attack_target", "advance_phase"})

    def test_greedy_ordering_still_matches_the_legacy_phase_sequence(self):
        """Category-major priority keeps every `max(actions, key=priority)`
        consumer in the repo picking what the old fixed phases produced."""
        session = create_session(seed=7)
        session.active_player = "player"
        session.player.gold = 9
        session.player.combat = 5
        actions = session.legal_actions()
        self.assertEqual(actions[0]["type"], "play_card")
        best = max(actions, key=lambda a: a["priority"])
        self.assertEqual(best["type"], "play_card")
        # Raw priorities survive for anything that needs the true value.
        self.assertIn("rawPriority", actions[0])
        self.assertIn("categoryRank", actions[0])

    def test_advance_phase_ends_the_turn(self):
        session = create_session(seed=7)
        session.active_player = "player"
        self.assertEqual(session.phase, "main")
        session.advance_phase()
        self.assertEqual(session.active_player, "bot")

    def test_legacy_phases_still_work_for_baseline_reproduction(self):
        """Old harnesses set session.phase explicitly; that path is unchanged."""
        session = create_session(seed=7)
        session.active_player = "player"
        session.phase = "buy"
        self.assertEqual({a["type"] for a in session.legal_actions()},
                         {"advance_phase"})  # no gold yet, so only the pass
        session.advance_phase()
        self.assertEqual(session.phase, "combat")


class TestGrakLogsNothing(unittest.TestCase):
    """Grak's expend is mechanically correct but silent in the log, which is
    why a player reported it as a suspected rules bug."""

    def test_expend_draws_and_discards_but_says_neither(self):
        from hero_engine import load_hero_cards

        cards = {c.name: c for c in load_hero_cards("data/hero_realms_cards.json")}
        session = create_session(seed=7)
        session.active_player, session.phase = "player", "champion"
        grak = BoardChampion(cards["Grak, Storm Giant"])
        session.player.board.append(grak)
        deck_before, discard_before = len(session.player.deck), len(session.player.discard)

        session.expend_champion_action(str(grak.instance_id))

        self.assertEqual(session.player.combat, 6)
        self.assertEqual(len(session.player.deck), deck_before - 1, "drew a card")
        self.assertEqual(len(session.player.discard), discard_before + 1, "discarded one")

        messages = " ".join(entry["message"] for entry in session.log)
        self.assertIn("Grak", messages)
        # Current behaviour: the draw/discard is invisible. If this ever starts
        # being logged, delete the assertion rather than the logging.
        self.assertNotIn("drew", messages.lower())

if __name__ == "__main__":
    unittest.main()
