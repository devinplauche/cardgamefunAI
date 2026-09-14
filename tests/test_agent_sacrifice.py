"""Optional sacrifices must be the agent's decision, not the engine's.

Found by playing the web UI and insisting on making every move by hand:

  * playing a Fire Gem silently banished it for +3 combat, and
  * expending Lys silently removed a card from hand,

with no prompt, no log line, and no corresponding entry in `legal_actions()` -
so MCTS could not search either one. Same failure mode as the phase ratchet:
not a worse policy, an unreachable one.

These tests pin both halves: the legacy behaviour with the flag off (so the
existing baselines stay reproducible) and the decision being reachable with it
on.
"""
import pytest

import hero_engine
from hero_engine import FIRE_GEM, GOLD, SHORTSWORD
from web.session import GameSession


@pytest.fixture
def agent_chooses():
    """Enable the flag for one test and put it back afterwards."""
    before = hero_engine.AGENT_CHOOSES_SACRIFICE
    hero_engine.AGENT_CHOOSES_SACRIFICE = True
    yield
    hero_engine.AGENT_CHOOSES_SACRIFICE = before


def _session(hand):
    session = GameSession(seed=7, algorithm="heuristic", budget_ms=1)
    player = session.player
    player.hand = list(hand)
    player.combat = 0
    player.gold = 0
    player.played_this_turn.clear()
    player.banish.clear()
    player.effect_log.clear()
    # _should_self_sacrifice takes the bonus only once the deck already owns a
    # couple of non-starting economy cards; give it two so the legacy path
    # actually fires and the flag's effect is what the test isolates.
    player.discard = [FIRE_GEM, FIRE_GEM]
    return session


def _types(session):
    return [a["type"] for a in session.legal_actions()]


def test_legacy_fire_gem_self_sacrifices_without_being_asked():
    """The behaviour every existing baseline was measured against."""
    session = _session([FIRE_GEM])
    session.play_card(FIRE_GEM.id)

    assert session.player.gold == 2
    assert session.player.combat == 3, "legacy path takes the sacrifice itself"
    assert FIRE_GEM not in session.player.played_this_turn
    assert "sacrifice_played" not in _types(session)


def test_fire_gem_sacrifice_becomes_a_legal_action(agent_chooses):
    session = _session([FIRE_GEM])
    session.play_card(FIRE_GEM.id)

    assert session.player.gold == 2
    assert session.player.combat == 0, "the engine must not decide this"
    assert FIRE_GEM in session.player.played_this_turn
    assert "sacrifice_played" in _types(session)

    session.sacrifice_played_action(FIRE_GEM.id)
    assert session.player.combat == 3
    assert FIRE_GEM in session.player.banish
    assert FIRE_GEM not in session.player.played_this_turn


def test_declining_the_sacrifice_is_reachable(agent_chooses):
    """"You may sacrifice" - keeping a recurring 2-gold source has to stay
    playable, and under the legacy path it was not."""
    session = _session([FIRE_GEM])
    session.play_card(FIRE_GEM.id)
    session.advance_phase()          # end turn without ever sacrificing

    assert FIRE_GEM not in session.player.banish


def _lys(session):
    lys = next(c for c in session.cards if c.name == "Lys, the Unseen")
    session.player.hand = [lys, GOLD, SHORTSWORD]
    session.play_card(lys.id)
    return lys


def test_legacy_expend_sacrifice_silently_eats_a_card():
    session = _session([])
    _lys(session)
    before = list(session.player.hand)

    champion = session.player.board[-1]
    session.expend_champion_action(str(champion.instance_id))

    assert len(session.player.hand) == len(before) - 1
    assert session.player.combat == 4, "2 base + 2 for the sacrifice"


def test_expend_sacrifice_offers_one_action_per_candidate(agent_chooses):
    session = _session([])
    _lys(session)
    champion = session.player.board[-1]

    sacrifices = [a for a in session.legal_actions()
                  if a["type"] == "expend_champion" and "sacrificeIndex" in a]
    plain = [a for a in session.legal_actions()
             if a["type"] == "expend_champion" and "sacrificeIndex" not in a]

    assert plain, "declining must stay available"
    names = {a["label"] for a in sacrifices}
    assert any("Gold" in n for n in names)
    assert any("Shortsword" in n for n in names)

    chosen = next(a for a in sacrifices if "Gold" in a["label"])
    session.expend_champion_action(str(champion.instance_id),
                                   sacrifice_index=chosen["sacrificeIndex"],
                                   sacrifice_zone=chosen["sacrificeZone"])

    assert session.player.combat == 4
    assert GOLD in session.player.banish
    assert SHORTSWORD in session.player.hand, "the agent's pick must be honoured"


def test_expend_can_decline_the_sacrifice(agent_chooses):
    session = _session([])
    _lys(session)
    champion = session.player.board[-1]
    before = list(session.player.hand)

    session.expend_champion_action(str(champion.instance_id))

    assert session.player.combat == 2, "base only, no sacrifice bonus"
    assert session.player.hand == before
    assert not session.player.banish


def test_engine_resolved_effects_reach_the_visible_log():
    """A sacrifice mutates a zone with no action taken for it, so nothing else
    knows to log it. Lys removed a card from hand and the log said nothing."""
    session = _session([])
    _lys(session)
    champion = session.player.board[-1]
    session.expend_champion_action(str(champion.instance_id))

    messages = [e["message"] for e in session.log if e["kind"] == "effect"]
    assert any("Sacrificed" in m for m in messages), messages


def test_sacrifice_up_to_still_fires_under_the_flag(agent_chooses):
    """Regression: gating `sacrifice_up_to` on the flag without an action to
    replace it made Tyrannor's ability do nothing at all.

    A dead ability is strictly worse than one the engine resolves - it is the
    exact failure this flag exists to remove. `sacrifice_up_to` is a multi-card
    selection that one expend action cannot express, so it stays engine-resolved
    until the pending_choices queue is plumbed through.
    """
    session = _session([])
    tyrannor = next(c for c in session.cards if c.name.startswith("Tyrannor"))
    session.player.hand = [tyrannor, GOLD, SHORTSWORD]
    session.play_card(tyrannor.id)

    champion = session.player.board[-1]
    session.expend_champion_action(str(champion.instance_id))

    assert session.player.banish, "the ability must still do something"
    messages = [e["message"] for e in session.log if e["kind"] == "effect"]
    assert any("Sacrificed" in m for m in messages), messages


def test_engine_resolved_effects_are_never_silent():
    """Every zone the engine mutates on its own has to say so. Each of these
    changed the board with nothing in the log until the UI playthrough found
    them."""
    session = _session([])
    smash = next(c for c in session.cards if c.name == "Smash and Grab")
    session.player.hand = [smash]
    session.player.discard = [GOLD, SHORTSWORD]
    session.play_card(smash.id)

    messages = [e["message"] for e in session.log if e["kind"] == "effect"]
    assert any("Recycled" in m for m in messages), messages


def test_forced_opponent_discard_is_logged_against_the_victim():
    session = _session([])
    curse = next(c for c in session.cards if c.name == "Elven Curse")
    session.player.hand = [curse]
    session.play_card(curse.id)

    messages = [e["message"] for e in session.log if e["kind"] == "effect"]
    assert any("forced" in m and session.bot.name in m for m in messages), messages


def test_simulation_clones_do_not_build_narration():
    """play_card runs ~25k times per MCTS decision; the log is pure waste
    there and must be switched off."""
    session = _session([FIRE_GEM])
    clone = session.clone()

    assert clone.player.log_effects is False
    assert clone.bot.log_effects is False

    clone.play_card(FIRE_GEM.id)
    assert clone.player.effect_log == []
    assert session.player.log_effects is True
