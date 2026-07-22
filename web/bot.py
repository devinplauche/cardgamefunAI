from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import math
import random
from typing import Any

from hero_engine import has_ally, play_card, buy_card, expend_champion


@dataclass
class Node:
    action: dict[str, Any] | None
    parent: "Node | None" = None
    visits: int = 0
    reward: float = 0.0
    children: list["Node"] = None
    untried_actions: list[dict[str, Any]] = None
    # Seat that took `action`. Rewards are always stored from the bot's point of
    # view, so opponent nodes have to be selected by minimising them.
    actor: str = "bot"

    def __post_init__(self) -> None:
        self.children = [] if self.children is None else self.children
        self.untried_actions = [] if self.untried_actions is None else self.untried_actions

    def uct_score(self, exploration: float = 1.35, lo: float = 0.0, hi: float = 1.0,
                  maximize: bool = True) -> float:
        """UCT with the exploitation term normalised into [0, 1].

        The exploration constant is only meaningful against rewards on a unit
        scale. Raw evaluate_state output runs to hundreds (health difference
        x10) and +/-10000 at terminals, which made the exploration term of
        ~2.6 numerically invisible: the first child expanded kept winning every
        comparison on its single noisy rollout and the rest were never revisited
        (measured 31 of 36 visits on one child, 1 each on the others).

        lo/hi are the reward range observed so far in this search.
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


WIN_SCORE = 10_000.0

# turn_number increments once per seat, so this is ~2 full rounds. The horizon
# has to be long enough for a bought card to be shuffled in, drawn, and used,
# or search-priced evaluation cannot see what a purchase bought.
ROLLOUT_TURNS = 4

# "search" prices nothing and lets rollouts decide; "shaped" uses the static
# weights below. Kept switchable so the two can be benchmarked head to head.
EVAL_MODE = "search"

# Phases worth spending search on. Play and champion phases are auto-resolved
# greedily; see the note in choose_bot_action.
SEARCHED_PHASES = ("buy", "combat")


def evaluate_state(session) -> float:
    """Score a position by the win condition alone.

    Nothing here prices gold, combat, draw, or board development. Those are
    worth exactly what the rollout converts them into, which is the point: the
    gold-to-combat exchange rate is situational, and any fixed weight asserts a
    tradeoff that is wrong at some point in every game.

    This is only sound because _rollout plays whole turns for both seats. With
    a horizon that ends at the bot's own end of turn, a purchase never gets
    drawn and buying correctly looks worthless.
    """
    if session.winner == "bot":
        return WIN_SCORE
    if session.winner == "player":
        return -WIN_SCORE
    return (session.bot.hp - session.player.hp) * 10.0


def evaluate_state_shaped(session) -> float:
    """Hand-priced evaluation, retained for A/B comparison against search."""
    player = session.bot
    opponent = session.player

    score = (player.hp - opponent.hp) * 10.0
    score += (_deck_quality(player) - _deck_quality(opponent)) * DECK_QUALITY_WEIGHT
    score += _board_value(player.board) - _board_value(opponent.board)
    score += player.gold * 0.5
    score += player.combat * 1.5
    return score


def _leaf_value(session) -> float:
    if EVAL_MODE == "shaped":
        return evaluate_state_shaped(session)
    return evaluate_state(session)


def legal_actions(session) -> list[dict[str, Any]]:
    return session.legal_actions()


def apply_action(session, action: dict[str, Any]) -> None:
    action_type = action["type"]
    if action_type == "play_card":
        session.play_card(action["cardId"])
    elif action_type == "expend_champion":
        session.expend_champion_action(action["championId"])
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
        "target": action.get("target"),
    }
    for key in ("score", "visits", "averageScore", "priority"):
        if key in action:
            summary[key] = action[key]
    return summary


def _heuristic_rollout_action(session) -> dict[str, Any]:
    actions = _sorted_actions(legal_actions(session))
    if not actions:
        return {"type": "advance_phase"}

    phase = session.phase
    if phase == "play":
        for action in actions:
            if action["type"] == "play_card":
                return action
    elif phase == "champion":
        for action in actions:
            if action["type"] == "expend_champion":
                return action
    elif phase == "buy":
        for action in actions:
            if action["type"] == "buy_card":
                return action
    elif phase == "combat":
        for action in actions:
            if action["type"] == "attack_target":
                return action
    return actions[0]


def _rollout(session, turn_limit: int | None = None, action_cap: int = 400) -> float:
    """Play both seats forward greedily, then score the resulting position.

    This used to stop the moment the turn passed to the opponent, so the bot
    never simulated being hit and never saw a purchase come back around. Both
    seats are now played out: _heuristic_rollout_action acts for whichever seat
    is current, so the same policy drives both.
    """
    # Read at call time, not bound as a default, so the constant stays tunable.
    turn_limit = ROLLOUT_TURNS if turn_limit is None else turn_limit
    start_turn = session.turn_number
    actions = 0
    while (not session.winner
           and session.turn_number - start_turn < turn_limit
           and actions < action_cap):
        if not legal_actions(session):
            break
        apply_action(session, _heuristic_rollout_action(session))
        actions += 1
    return _leaf_value(session)


def _best_child(node: Node, lo: float = 0.0, hi: float = 1.0) -> Node:
    return max(node.children, key=lambda child: child.uct_score(lo=lo, hi=hi))


def _action_key(action: dict[str, Any] | None) -> tuple:
    if action is None:
        return ()
    return (
        action.get("type"),
        action.get("cardId"),
        action.get("marketIndex"),
        action.get("championId"),
        action.get("target"),
    )


def _legal_keys(session) -> set[tuple]:
    return {_action_key(action) for action in legal_actions(session)}


def _root_candidates_from_children(root: Node) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for child in root.children:
        if child.action is None:
            continue
        average = child.reward / child.visits if child.visits else 0.0
        payload = _action_summary(child.action)
        payload["visits"] = child.visits
        payload["averageScore"] = round(average, 3)
        candidates.append(payload)
    # Ranked by visits first so the displayed order matches how the action is
    # actually chosen (robust child), not a separate score ordering.
    return sorted(candidates, key=lambda item: (item.get("visits", 0), item.get("averageScore", float("-inf"))), reverse=True)


def choose_bot_action(session, budget_ms: int = 60, algorithm: str = "mcts") -> dict[str, Any]:
    start = perf_counter()
    actions = _sorted_actions(legal_actions(session))
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
        candidates = [_action_summary(action) for action in actions[:3]]
        return {
            **chosen,
            "score": evaluate_state(session.clone()) if hasattr(session, "clone") else 0.0,
            "iterations": 1,
            "elapsedMs": int((perf_counter() - start) * 1000),
            "algorithm": "heuristic",
            "candidates": candidates,
        }

    root = Node(action=None, untried_actions=actions[:])
    iterations = 0
    best_action = actions[0]
    best_score = float("-inf")
    # Reward range observed in this search, used to normalise UCT's exploitation
    # term. Seeded from the first rollout rather than assumed.
    reward_lo = float("inf")
    reward_hi = float("-inf")

    while (perf_counter() - start) * 1000 < budget_ms:
        sim = session.clone()
        node = root
        path = [node]

        # end_turn() draws 5 cards at random, so replaying the same action
        # sequence does not reproduce the same state. Actions cached in the tree
        # can therefore be illegal in this sample, which used to raise out of
        # apply_action. Re-check legality against the sampled state at each step.
        while not node.untried_actions and node.children and not sim.winner:
            legal = _legal_keys(sim)
            viable = [c for c in node.children if _action_key(c.action) in legal]
            if not viable:
                break
            # All children of a node are moves from the same position, so they
            # share an actor. The bot maximises; the opponent minimises.
            maximize = sim.active_player == "bot"
            node = max(viable, key=lambda child: child.uct_score(
                lo=reward_lo, hi=reward_hi, maximize=maximize))
            apply_action(sim, node.action)
            path.append(node)

        if node.untried_actions and not sim.winner:
            legal = _legal_keys(sim)
            # Leave actions that are illegal in this sample for a later one
            # instead of discarding them.
            action = next((a for a in node.untried_actions if _action_key(a) in legal), None)
            if action is not None:
                actor = sim.active_player
                node.untried_actions.remove(action)
                apply_action(sim, action)
                child = Node(action=action, parent=node, actor=actor,
                             untried_actions=_sorted_actions(legal_actions(sim)))
                node.children.append(child)
                node = child
                path.append(node)

        reward = _rollout(sim)
        reward_lo = min(reward_lo, reward)
        reward_hi = max(reward_hi, reward)

        for item in path:
            item.visits += 1
            item.reward += reward
        iterations += 1

    candidates = _root_candidates_from_children(root)
    if root.children:
        # Robust-child selection: take the most-visited root child.
        #
        # This used to track the best single rollout reward over any node at any
        # depth, then map it back to a root child by (type, label). But
        # "advance_phase"/"Next Phase" exists in every phase, so a pass from deep
        # inside a rollout routinely matched the root's pass and overrode the
        # search. Measured at one combat decision: attack scored 112.58 over 59
        # visits, pass scored -10.58 over 1 visit, and the bot returned pass.
        best = max(root.children, key=lambda child: (child.visits, child.reward / child.visits if child.visits else float("-inf")))
        best_action = best.action
        best_score = best.reward / best.visits if best.visits else 0.0

    return {
        **best_action,
        "score": round(best_score, 3),
        "iterations": iterations,
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

        chosen = choose_bot_action(session, max(20, budget_ms // 2), algorithm=algorithm)
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
