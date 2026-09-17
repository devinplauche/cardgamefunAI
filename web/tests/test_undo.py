"""Engine-level single-step Undo: snapshot/restore round-trip tests.

Covers web.games.snapshot / web.games.restore: a snapshot must capture
everything a player mutation can change, restore must return the session to
byte-equivalence (a fresh snapshot afterwards compares equal), the snapshot
must be plain JSON-serializable (the integration owner persists it), and the
card population (tracked by per-copy uid) must be conserved through the
cycle - even when a mutation creates a card (buying a Fire Gem deep-copies
one) or destroys the physical object (a sacrificed Fire Gem returns to the
pile as a count, the HRCard is dropped).
"""

import copy
import json
import unittest
from collections import Counter

import hero_engine
from web import games
from web.session import create_session


def _snapshot_population(snap):
    """Multiset of card uids across every zone captured in a snapshot."""
    counts = Counter()
    for side in ("player", "bot"):
        p = snap[side]
        for zone in (
            "deck",
            "hand",
            "discard",
            "banish",
            "played_this_turn",
            "pending_ally",
            "available_ally_triggers",
        ):
            counts.update(c["uid"] for c in p[zone])
        counts.update(c["card"]["uid"] for c in p["board"])
        for entry in p["pending_per_champion"]:
            counts[entry["card"]["uid"]] += 1
    market = snap["market"]
    counts.update(c["uid"] for c in market["pool"])
    counts.update(c["uid"] for c in market["row"] if c is not None)
    return counts


def _live_population(session):
    """Multiset of card uids across every zone of the live session."""
    counts = Counter()
    for player in (session.player, session.bot):
        for zone in (
            "deck",
            "hand",
            "discard",
            "banish",
            "played_this_turn",
            "pending_ally",
            "available_ally_triggers",
        ):
            counts.update(c.uid for c in getattr(player, zone))
        counts.update(c.card.uid for c in player.board)
        for entry in player.pending_per_champion:
            counts[entry["card"].uid] += 1
    counts.update(c.uid for c in session.market.pool)
    counts.update(c.uid for c in session.market.row if c is not None)
    return counts


def _scrimmage(session):
    """A deterministic burst of player mutations: play, buy, attack, end turn."""
    player = session.player
    for card in list(player.hand):
        try:
            session.play_card(card.id)
        except ValueError:
            break
    if player.gold >= 2 and session.market.can_buy_fire_gem():
        # Buys a Fire Gem: the engine deep-copies one, minting a fresh uid.
        session.buy_card_action(5)
    else:
        affordable = [
            (i, c)
            for i, c in enumerate(session.market.row_cards())
            if c is not None and c.cost <= player.gold
        ]
        if affordable:
            session.buy_card_action(min(affordable, key=lambda t: t[1].cost)[0])
    if player.combat > 0:
        try:
            session.attack_target_action("player")
        except ValueError:
            pass
    session.end_turn()


class TestUndoSnapshotRestore(unittest.TestCase):
    def test_snapshot_is_json_serializable(self):
        session = create_session(seed=42)
        snap = games.snapshot(session)
        # Must not raise: the integration owner persists snapshots as JSON.
        json.dumps(snap)

    def test_mutate_snapshot_mutate_restore_equals_snapshot(self):
        session = create_session(seed=7)
        snap = games.snapshot(session)
        _scrimmage(session)
        # The scrimmage really did mutate the state...
        self.assertNotEqual(games.snapshot(session), snap)
        # ...and restore returns it to byte-equivalence.
        games.restore(session, snap)
        self.assertEqual(games.snapshot(session), snap)

    def test_restore_from_json_round_trip(self):
        # The realistic path: snapshot -> JSON text in a DB column ->
        # parsed dict -> restore. The parsed form must restore identically.
        session = create_session(seed=7)
        snap = games.snapshot(session)
        persisted = json.loads(json.dumps(snap))
        _scrimmage(session)
        games.restore(session, persisted)
        self.assertEqual(games.snapshot(session), snap)

    def test_multiple_snapshots_restore_independently(self):
        session = create_session(seed=7)
        snap1 = games.snapshot(session)
        _scrimmage(session)
        snap2 = games.snapshot(session)
        self.assertNotEqual(snap1, snap2)
        session.play_card(session.player.hand[0].id)
        games.restore(session, snap2)
        self.assertEqual(games.snapshot(session), snap2)
        games.restore(session, snap1)
        self.assertEqual(games.snapshot(session), snap1)

    def test_card_population_conserved(self):
        session = create_session(seed=7)
        snap = games.snapshot(session)
        _scrimmage(session)
        games.restore(session, snap)
        # Every zone the snapshot captured is back exactly; nothing created
        # or destroyed by the scrimmage (bought Fire Gems, spent combat,
        # discarded hands) leaks through the restore.
        self.assertEqual(_live_population(session), _snapshot_population(snap))

    def test_rng_state_restored(self):
        session = create_session(seed=99)
        snap = games.snapshot(session)
        state_at_snap = session.rng.getstate()
        # Consume RNG output through the shared object (draws and shuffles
        # go through it); a turn's card play need not touch it at all.
        session.rng.random()
        session.rng.shuffle(session.player.deck)
        self.assertNotEqual(session.rng.getstate(), state_at_snap)
        games.restore(session, snap)
        self.assertEqual(session.rng.getstate(), state_at_snap)
        # ...and the players still draw from the live RNG object.
        self.assertIs(session.player._rng, session.rng)
        self.assertIs(session.bot._rng, session.rng)
        # The restored RNG drives future draws deterministically.
        first = [session.rng.random() for _ in range(3)]
        games.restore(session, snap)
        second = [session.rng.random() for _ in range(3)]
        self.assertEqual(first, second)

    def test_sacrifice_drops_physical_card_yet_restores(self):
        # A sacrificed Fire Gem returns to the pile as a *count*: its HRCard
        # object is dropped from every zone. Restore must still reproduce
        # the snapshot exactly, uid included.
        session = create_session(seed=11)
        gem = copy.deepcopy(hero_engine.FIRE_GEM)
        session.player.hand.append(gem)
        snap = games.snapshot(session)
        session.play_card("fire_gem")
        session.sacrifice_played_action("fire_gem")
        self.assertEqual(session.market.fire_gems_remaining, 17)
        self.assertEqual(session.player.combat, 3)
        games.restore(session, snap)
        self.assertEqual(games.snapshot(session), snap)
        self.assertEqual(session.market.fire_gems_remaining, 16)
        self.assertEqual(session.player.combat, 0)
        restored_uids = [c.uid for c in session.player.hand if c.id == "fire_gem"]
        self.assertEqual(restored_uids, [gem.uid])

    def test_duplicate_copies_keep_distinct_uids(self):
        # Two copies of one card share card.id; the snapshot keys them by
        # uid so they restore as distinct physical cards, not one object.
        session = create_session(seed=7)
        session.player.hand.extend(
            [copy.deepcopy(hero_engine.GOLD), copy.deepcopy(hero_engine.GOLD)]
        )
        uids_before = [c.uid for c in session.player.hand if c.id == "gold"]
        self.assertEqual(len(set(uids_before)), len(uids_before))
        snap = games.snapshot(session)
        session.play_card("gold")
        games.restore(session, snap)
        uids_after = [c.uid for c in session.player.hand if c.id == "gold"]
        self.assertEqual(uids_before, uids_after)
        self.assertEqual(len(set(uids_after)), len(uids_after))

    def test_pending_choice_round_trip(self):
        # With AGENT_CHOOSES_TARGETS (production), playing Elven Gift
        # enqueues a discard choice instead of auto-resolving it.
        before = hero_engine.AGENT_CHOOSES_TARGETS
        hero_engine.AGENT_CHOOSES_TARGETS = True
        try:
            session = create_session(seed=21)
            gift = copy.deepcopy(
                next(c for c in session.cards if c.id == "hr_046")
            )
            session.player.hand.append(gift)
            session.play_card("hr_046")
            self.assertTrue(session.player.pending_choices)
            snap = games.snapshot(session)
            json.dumps(snap)
            session.resolve_choice_action(0)
            self.assertFalse(session.player.pending_choices)
            games.restore(session, snap)
            self.assertEqual(games.snapshot(session), snap)
            self.assertTrue(session.player.pending_choices)
            self.assertEqual(
                session.player.pending_choices[0]["kind"], "discard"
            )
        finally:
            hero_engine.AGENT_CHOOSES_TARGETS = before

    def test_winner_and_turn_state_restored(self):
        session = create_session(seed=7)
        snap = games.snapshot(session)
        session.end_turn()
        self.assertEqual(session.active_player, "bot")
        self.assertNotEqual(session.turn_number, snap["turn_number"])
        games.restore(session, snap)
        self.assertEqual(session.active_player, snap["active_player"])
        self.assertEqual(session.turn_number, snap["turn_number"])
        self.assertEqual(session.phase, snap["phase"])
        self.assertEqual(session.winner, snap["winner"])

    def test_session_usable_after_restore(self):
        session = create_session(seed=7)
        snap = games.snapshot(session)
        _scrimmage(session)
        restored = games.restore(session, snap)
        self.assertIs(restored, session)
        # The restored session is fully playable, not a hollow copy.
        session.play_card(session.player.hand[0].id)
        self.assertEqual(len(session.player.played_this_turn), 1)


if __name__ == "__main__":
    unittest.main()
