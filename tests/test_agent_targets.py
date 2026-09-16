"""Sacrifice/discard *targeting* as a real decision (AGENT_CHOOSES_TARGETS).

`defer_choices` and the pending-choices queue have existed for a while, but
only `hero_rl_env_v3.py` ever set the flag - the MCTS bot never did. So
`_find_worst_idx`, which fires ~14 times per game, chose which card to
sacrifice and which to discard on the bot's behalf. These are, by
`hero_engine.py`'s own comment, "the decisions a strong player spends the most
thought on".
"""
import pytest

import hero_engine
from hero_engine import GOLD, SHORTSWORD
from web.session import GameSession


@pytest.fixture
def agent_targets():
    before = hero_engine.AGENT_CHOOSES_TARGETS
    hero_engine.AGENT_CHOOSES_TARGETS = True
    yield
    hero_engine.AGENT_CHOOSES_TARGETS = before


def _session(hand_names, seed=11):
    session = GameSession(seed=seed, algorithm="heuristic", budget_ms=1)
    by_name = {c.name: c for c in session.cards}
    session.player.hand = [by_name[n] if n in by_name else n for n in hand_names]
    session.player.combat = 0
    session.player.gold = 0
    session.player.played_this_turn.clear()
    session.player.banish.clear()
    return session


def test_legacy_targeting_is_silent_and_unreachable():
    """What every existing baseline measured."""
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    death_touch = session.player.hand[0]
    session.play_card(death_touch.id)

    assert not session.player.pending_choices
    assert "resolve_choice" not in {a["type"] for a in session.legal_actions()}
    assert session.player.banish, "engine sacrificed something on its own"


def test_targeting_becomes_a_legal_action(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    death_touch = session.player.hand[0]
    session.play_card(death_touch.id)

    assert session.player.pending_choices, "the effect must wait for a target"
    actions = session.legal_actions()
    assert {a["type"] for a in actions} == {"resolve_choice"}, (
        "a half-resolved effect must block everything else")

    labels = [a["label"] for a in actions]
    assert any("Gold" in label for label in labels)
    assert any("Shortsword" in label for label in labels)
    assert any("Decline" in label for label in labels), "'you may sacrifice'"


def test_the_agents_pick_is_honoured(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    chosen = next(a for a in session.legal_actions() if "Shortsword" in a["label"])
    session.resolve_choice_action(chosen["candidateIndex"])

    assert SHORTSWORD in session.player.banish
    assert GOLD in session.player.hand, "the heuristic would have taken the Gold"
    assert not session.player.pending_choices


def test_declining_is_reachable(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    decline = next(a for a in session.legal_actions() if a["candidateIndex"] < 0)
    session.resolve_choice_action(decline["candidateIndex"])

    assert not session.player.banish
    assert not session.player.pending_choices
    assert "play_card" in {a["type"] for a in session.legal_actions()}


def test_a_forced_discard_cannot_be_declined(agent_targets):
    """Elven Gift is "draw a card, then discard a card" - not optional."""
    session = _session(["Elven Gift"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    actions = session.legal_actions()
    assert actions and {a["type"] for a in actions} == {"resolve_choice"}
    assert not any(a["candidateIndex"] < 0 for a in actions), "discard is forced"


def test_bot_can_play_a_whole_turn_with_targeting_on(agent_targets):
    """The queue blocks every other action, so a bot that cannot answer it
    would deadlock. This is the check that matters before any A/B.

    The bot's hand is seeded with a sacrifice card and the choice is spied on,
    so the test fails loudly if it ever stops exercising the path rather than
    passing vacuously.
    """
    session = GameSession(seed=4, algorithm="mcts", budget_ms=20)
    by_name = {c.name: c for c in session.cards}
    session.bot.hand = [by_name["Death Touch"], GOLD, SHORTSWORD]
    session.active_player = "bot"

    seen = []
    original = session.legal_actions

    def spy():
        actions = original()
        if actions and actions[0]["type"] == "resolve_choice":
            seen.append(len(actions))
        return actions

    session.legal_actions = spy
    session.run_bot_turn()

    assert seen, "the bot never faced the decision; this test proved nothing"
    assert not session.bot.pending_choices, "bot left a choice unresolved"
    assert session.active_player == "player"


def test_tyrannor_sacrifice_is_a_two_pick_player_choice(agent_targets):
    """Tyrannor's "you may sacrifice up to two" enqueues one choice answered
    twice; declining stops early. The source names the card for the sheet."""
    session = _session(["Tyrannor, the Devourer"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.player.discard = [GOLD]
    session.play_card(session.player.hand[0].id)

    champion = session.player.board[-1]
    session.expend_champion_action(str(champion.instance_id))

    assert len(session.player.pending_choices) == 1
    choice = session.player.pending_choices[0]
    assert choice["kind"] == "sacrifice" and choice["count"] == 2
    assert choice["zone"] == "hand_or_discard"
    assert choice["source"] == "Tyrannor, the Devourer"
    assert not session.player.banish, "nothing sacrificed until the player picks"

    actions = session.legal_actions()
    assert {a["type"] for a in actions} == {"resolve_choice"}, \
        "a half-resolved effect must block everything else"
    assert all(a.get("remaining") == 2 for a in actions)
    assert any(a["candidateIndex"] < 0 for a in actions), "'you may' is declinable"

    first = next(a for a in actions if a["candidateIndex"] >= 0)
    session.resolve_choice_action(first["candidateIndex"])
    assert len(session.player.pending_choices) == 1, "one pick left"
    assert len(session.player.banish) == 1

    actions = session.legal_actions()
    assert all(a.get("remaining") == 1 for a in actions), \
        "the sheet must know one pick is left"

    decline = next(a for a in actions if a["candidateIndex"] < 0)
    session.resolve_choice_action(decline["candidateIndex"])
    assert not session.player.pending_choices
    assert len(session.player.banish) == 1, "declining stops at one"


def test_bot_answers_a_multi_pick_sacrifice(agent_targets):
    """Tyrannor through the bot's own turn: it sacrifices the junk, declines
    the rest, and never leaves the choice hanging."""
    from hero_engine import BoardChampion
    session = GameSession(seed=4, algorithm="heuristic", budget_ms=20)
    by_name = {c.name: c for c in session.cards}
    good = next(c for c in session.cards if c.get("gold", 0) > 0 and c.cost >= 2)
    session.bot.hand = []
    session.bot.discard = [GOLD, SHORTSWORD, good]
    champion = BoardChampion(by_name["Tyrannor, the Devourer"])
    session.bot.board.append(champion)
    session.active_player = "bot"

    session.expend_champion_action(str(champion.instance_id))
    assert session.bot.pending_choices, "expected the two-pick choice"

    session.run_bot_turn()

    assert not session.bot.pending_choices, "bot left a choice unresolved"
    assert len(session.bot.banish) == 2, \
        f"bot should thin exactly the junk, banished {[c.name for c in session.bot.banish]}"
    assert good in session.bot.discard, "the good card must survive"

# ---------------------------------------------------------------------------
# Ally triggers: the bot must fire them (they used to be automatic).
# ---------------------------------------------------------------------------
from hero_engine import BoardChampion
from web.bot import apply_action, choose_bot_action, run_bot_turn


def _bot_session(hand_names, board_names=(), seed=11):
    """A session parked on the bot's turn, with a rigged hand and board."""
    session = GameSession(seed=seed, algorithm="heuristic", budget_ms=1)
    by_name = {c.name: c for c in session.cards}
    session.active_player = "bot"
    session.bot.hand = [by_name[n] for n in hand_names]
    session.bot.board = [BoardChampion(by_name[n]) for n in board_names]
    session.bot.deck = list(session.bot.deck)
    return session, by_name


def test_bot_fires_a_draw_ally_trigger(agent_targets):
    """Dark Energy's ally (draw a card) is free value the engine used to grant
    automatically. The bot must fire it rather than leave it on the table.

    Playing Dark Energy also completes Tyrannor's faction pair, so the board
    champion's own draw trigger is offered too - the bot must work through
    both, one decision at a time."""
    session, by_name = _bot_session(
        ["Dark Energy"], board_names=["Tyrannor, the Devourer"])
    session.bot.deck = [GOLD, SHORTSWORD] + session.bot.deck
    session.play_card(by_name["Dark Energy"].id)

    assert {c.name for c in session.bot.available_ally_triggers} == {
        "Dark Energy", "Tyrannor, the Devourer"}
    hand_before = len(session.bot.hand)

    for _ in range(2):
        chosen = choose_bot_action(session, budget_ms=20, algorithm="heuristic")
        assert chosen["type"] == "trigger_ally", \
            f"bot left a free draw unfired: {chosen['type']}"
        apply_action(session, chosen)

    assert not session.bot.available_ally_triggers, "trigger must be consumed"
    assert len(session.bot.hand) == hand_before + 2, "ally draws never happened"


def test_bot_fires_trigger_before_mcts_combat_search(agent_targets):
    """With 7 combat banked and a live face attack, the search used to drop
    the trigger from the root action set and attack first - drawing after the
    attacks, when the drawn card can no longer be played. The trigger must
    win the root decision outright."""
    session, by_name = _bot_session(
        ["Dark Energy"], board_names=["Tyrannor, the Devourer"])
    session.bot.deck = [GOLD] + session.bot.deck
    session.play_card(by_name["Dark Energy"].id)
    assert session.bot.combat == 7
    assert any(a["type"] == "attack_target" for a in session.legal_actions())

    chosen = choose_bot_action(session, budget_ms=30, algorithm="mcts")
    assert chosen["type"] == "trigger_ally", \
        f"search stole the trigger decision: {chosen['type']}"


def test_bot_stun_ally_targets_the_biggest_threat(agent_targets):
    """Death Threat's ally stuns at trigger time. The bot must pick the most
    dangerous opposing champion, not the first target in the list."""
    session, by_name = _bot_session(
        ["Death Threat"], board_names=["Street Thug"], seed=12)
    session.player.board = [BoardChampion(by_name["Street Thug"]),
                            BoardChampion(by_name["Rake, Master Assassin"])]
    session.play_card(by_name["Death Threat"].id)

    triggers = [a for a in session.legal_actions() if a["type"] == "trigger_ally"]
    assert len(triggers) == 2, "one stun action per legal target"

    chosen = choose_bot_action(session, budget_ms=20, algorithm="heuristic")
    assert chosen["type"] == "trigger_ally"
    apply_action(session, chosen)

    # Stun destroys the champion, sweeping it to its owner's discard pile.
    assert "Rake, Master Assassin" in [c.name for c in session.player.discard], \
        "bot stunned the 3-cost thug instead of the 7-cost assassin"
    assert any(bc.alive and bc.card.name == "Street Thug"
               for bc in session.player.board)


def test_bot_whole_turn_fires_every_ally_trigger(agent_targets):
    """End to end across a full bot turn: every offered trigger fires, in the
    action stream, with its effect applied."""
    session, by_name = _bot_session(
        ["Dark Energy", "Profit"],
        board_names=["Tyrannor, the Devourer", "Street Thug"],
        seed=13)
    session.bot.deck = [GOLD] + session.bot.deck

    run_bot_turn(session, budget_ms=20, algorithm="heuristic")

    ally_labels = [e["label"] for e in session.history if e["kind"] == "ally"]
    assert any("Dark Energy" in label for label in ally_labels), \
        f"Dark Energy ally never fired: {ally_labels}"
    assert any("Profit" in label for label in ally_labels), \
        f"Profit ally never fired: {ally_labels}"
    assert not session.bot.available_ally_triggers, \
        "bot ended its turn with triggers still available"
