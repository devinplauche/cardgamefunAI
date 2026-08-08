import assert from "node:assert/strict";
import test from "node:test";
import {
  SUITS,
  advanceBots,
  chooseBotBid,
  chooseBotPlay,
  continueGame,
  createDeck,
  createGame,
  finishTrick,
  legalPlays,
  playCard,
  simulateGame,
  submitBid,
  type GameState,
} from "../lib/rage";

test("deck has the canonical 110 cards", () => {
  const deck = createDeck();
  assert.equal(deck.length, 110);
  assert.equal(new Set(deck.map((card) => card.id)).size, 110);
});
test("same seed produces an identical first deal", () => {
  const a = createGame({ seed: 42, playerCount: 4 });
  const b = createGame({ seed: 42, playerCount: 4 });
  assert.deepEqual(
    a.players.map((p) => p.hand),
    b.players.map((p) => p.hand),
  );
});
test("every player bids once before play begins", () => {
  let state = createGame({ seed: 4, playerCount: 3 });
  for (let i = 0; i < 3; i += 1)
    state = submitBid(state, state.currentPlayer, i);
  assert.equal(state.phase, "playing");
  assert.ok(state.players.every((player) => player.bid !== null));
});
test("follow suit restricts legal cards", () => {
  let state = createGame({ seed: 9, playerCount: 2 });
  state = submitBid(state, state.currentPlayer, 0);
  state = submitBid(state, state.currentPlayer, 0);
  const lead = state.players[state.currentPlayer].hand.find(
    (card) => card.suit,
  )!;
  state = playCard(state, state.currentPlayer, { cardId: lead.id });
  const legal = legalPlays(state);
  if (
    state.players[state.currentPlayer].hand.some(
      (card) => card.suit === lead.suit,
    )
  )
    assert.ok(legal.every((card) => card.suit === lead.suit));
});
test("all player counts and seed blocks complete ten rounds", () => {
  for (let players = 2; players <= 6; players += 1)
    for (let seed = 1; seed <= 20; seed += 1) {
      const game = simulateGame(
        seed,
        players,
        Array.from(
          { length: players },
          (_, i) =>
            ["easy", "medium", "hard"][i % 3] as "easy" | "medium" | "hard",
        ),
      );
      assert.equal(game.phase, "gameOver");
      assert.equal(game.round, 10);
      assert.equal(game.players.length, players);
      assert.ok(game.players.every((player) => Number.isFinite(player.score)));
    }
});
test("bot stepping stops for the human player", () => {
  let state = createGame({ seed: 77, playerCount: 4 });
  state = advanceBots(state, 0);
  assert.equal(state.currentPlayer, 0);
  assert.equal(state.phase, "bidding");
  void chooseBotBid;
  void chooseBotPlay;
  void continueGame;
  void SUITS;
});

function trickFixture(
  cards: [
    GameState["players"][number]["hand"],
    GameState["players"][number]["hand"],
  ],
): GameState {
  const base = createGame({ seed: 123, playerCount: 2 });
  return {
    ...base,
    phase: "playing",
    currentPlayer: 0,
    trump: "blue",
    players: base.players.map((player, index) => ({
      ...player,
      hand: cards[index],
      bid: 0,
      tricks: 0,
      roundBonus: 0,
    })),
    trick: [],
    leadSuit: null,
  };
}
test("Change and Out Rage update trump immediately", () => {
  const change = trickFixture([
    [{ id: "change", type: "change" }],
    [{ id: "red", suit: "red", rank: 2 }],
  ]);
  const changed = playCard(change, 0, { cardId: "change", chosenTrump: "red" });
  const randomlyChanged = playCard(change, 0, { cardId: "change" });
  assert.notEqual(changed.trump, "blue");
  assert.equal(changed.trump, randomlyChanged.trump);
  const out = trickFixture([
    [{ id: "out", type: "out" }],
    [{ id: "red", suit: "red", rank: 2 }],
  ]);
  assert.equal(playCard(out, 0, { cardId: "out" }).trump, null);
});
test("Wild Rage requires a declaration and Bonus Rage is scored for the trick winner", () => {
  const wild = trickFixture([
    [{ id: "wild", type: "wild" }],
    [{ id: "red", suit: "red", rank: 2 }],
  ]);
  assert.throws(() => playCard(wild, 0, { cardId: "wild" }), /declared suit/);
  assert.throws(
    () => playCard(wild, 0, { cardId: "wild", declaredSuit: "red" }),
    /declared number/,
  );
  const wildPlayed = playCard(wild, 0, {
    cardId: "wild",
    declaredSuit: "red",
    declaredRank: 1,
  });
  const wildScored = playCard(wildPlayed, 1, { cardId: "red" });
  assert.equal(wildScored.lastWinner, 1);
  const bonus = trickFixture([
    [{ id: "bonus", type: "bonus" }],
    [{ id: "green", suit: "green", rank: 2 }],
  ]);
  const afterBonus = playCard(bonus, 0, { cardId: "bonus" });
  const scored = playCard(afterBonus, 1, { cardId: "green" });
  assert.equal(scored.phase, "roundSummary");
  assert.equal(scored.lastRoundScores?.[1], 1);
});
test("the final card can remain visible before a trick resolves", () => {
  const state = trickFixture([
    [{ id: "red", suit: "red", rank: 7 }],
    [{ id: "red2", suit: "red", rank: 10 }],
  ]);
  const first = playCard(state, 0, { cardId: "red" }, true);
  const resolving = playCard(first, 1, { cardId: "red2" }, true);
  assert.equal(resolving.phase, "resolving");
  assert.equal(resolving.trick.length, 2);
  assert.equal(finishTrick(resolving).lastWinner, 1);
});
