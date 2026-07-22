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

    def __post_init__(self) -> None:
        self.children = [] if self.children is None else self.children
        self.untried_actions = [] if self.untried_actions is None else self.untried_actions

    def uct_score(self, exploration: float = 1.35) -> float:
        if self.visits == 0:
            return float("inf")
        assert self.parent is not None
        return (self.reward / self.visits) + exploration * math.sqrt(math.log(self.parent.visits + 1) / self.visits)


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


def evaluate_state(session) -> float:
    player = session.bot
    opponent = session.player
    score = (player.hp - opponent.hp) * 10.0
    score += (player.gold - opponent.gold) * 1.0
    score += player.combat * 1.5
    score += (len(player.hand) - len(opponent.hand)) * 0.75
    score += _board_value(player.board) - _board_value(opponent.board)
    score += session.market.fire_gems_remaining * 0.05
    return score


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


def _rollout(session, depth_limit: int = 10) -> float:
    depth = 0
    while depth < depth_limit and not session.winner:
        actions = legal_actions(session)
        if not actions:
            break
        action = _heuristic_rollout_action(session)
        apply_action(session, action)
        if action["type"] == "advance_phase" and session.phase == "play" and session.active_player == "player":
            break
        depth += 1
    return evaluate_state(session)


def _best_child(node: Node) -> Node:
    return max(node.children, key=lambda child: child.uct_score())


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
    return sorted(candidates, key=lambda item: (item.get("averageScore", float("-inf")), item.get("visits", 0)), reverse=True)


def choose_bot_action(session, budget_ms: int = 60, algorithm: str = "mcts") -> dict[str, Any]:
    start = perf_counter()
    actions = _sorted_actions(legal_actions(session))
    if not actions:
        return {"type": "advance_phase", "label": "Next Phase", "score": 0.0, "iterations": 0, "elapsedMs": 0}

    if algorithm != "mcts" or len(actions) == 1:
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
            node = max(viable, key=lambda child: child.uct_score())
            apply_action(sim, node.action)
            path.append(node)

        if node.untried_actions and not sim.winner:
            legal = _legal_keys(sim)
            # Leave actions that are illegal in this sample for a later one
            # instead of discarding them.
            action = next((a for a in node.untried_actions if _action_key(a) in legal), None)
            if action is not None:
                node.untried_actions.remove(action)
                apply_action(sim, action)
                child = Node(action=action, parent=node, untried_actions=_sorted_actions(legal_actions(sim)))
                node.children.append(child)
                node = child
                path.append(node)

        reward = _rollout(sim)
        if reward > best_score and node.action is not None:
            best_score = reward
            best_action = node.action

        for item in path:
            item.visits += 1
            item.reward += reward
        iterations += 1

    candidates = _root_candidates_from_children(root)
    if candidates:
        best_action = next(
            (item for item in candidates if item.get("type") == best_action.get("type") and item.get("label") == best_action.get("label")),
            candidates[0],
        )

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
