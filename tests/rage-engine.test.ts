import assert from "node:assert/strict";
import test from "node:test";
import {
  SUITS,
  advanceBots,
  chooseBotBid,
  chooseBotPlay,
  chooseMctsPlay,
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
test("trump is revealed by turning over stock cards until a color appears", () => {
  const game = createGame({ seed: 42, playerCount: 4 });
  const revealedTrump = game.trumpReveal.at(-1);
  assert.ok(game.trumpReveal.length >= 1);
  assert.equal(revealedTrump?.suit, game.trump);
  assert.ok(game.trumpReveal.slice(0, -1).every((card) => !card.suit));
  assert.ok(
    game.trumpReveal.every(
      (card) => !game.stock.some((stockCard) => stockCard.id === card.id),
    ),
  );
});
test("the first player is seeded-random instead of always being the human", () => {
  const games = Array.from({ length: 20 }, (_, seed) =>
    createGame({ seed: seed + 1, playerCount: 4 }),
  );
  const firstPlayers = new Set(games.map((game) => game.currentPlayer));
  assert.ok(firstPlayers.size > 1);
  assert.ok(games.every((game) => game.currentPlayer === game.leader));
});
test("the round leader advances clockwise after the opening round", () => {
  const state = createGame({ seed: 12, playerCount: 4 });
  const nextRound = continueGame({ ...state, phase: "roundSummary" });
  assert.equal(nextRound.leader, (state.leader! + 1) % state.playerCount);
  assert.equal(nextRound.currentPlayer, nextRound.leader);
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
test("MCTS selects a legal and deterministic play", () => {
  let state = createGame({ seed: 91, playerCount: 4 });
  for (let i = 0; i < 4; i += 1)
    state = submitBid(state, state.currentPlayer, 1);
  const playerId = state.currentPlayer;
  const first = chooseMctsPlay(state, playerId, { iterations: 8, rolloutPlies: 24 });
  const second = chooseMctsPlay(state, playerId, { iterations: 8, rolloutPlies: 24 });
  assert.deepEqual(first, second);
  assert.ok(legalPlays(state, playerId).some((card) => card.id === first.cardId));
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
test("Change Rage chooses its new trump only when played; Out Rage clears it", () => {
  const change = trickFixture([
    [{ id: "change", type: "change" }],
    [{ id: "red", suit: "red", rank: 2 }],
  ]);
  assert.equal(change.trump, "blue");
  assert.equal(change.trick[0], undefined);
  const played = playCard(
    {
      ...change,
      stock: [
        { id: "bonus-stock", type: "bonus" },
        { id: "red-stock", suit: "red", rank: 5 },
      ],
      trumpReveal: [],
    },
    0,
    { cardId: "change" },
  );
  assert.equal(played.trump, "red");
  assert.equal(played.trick[0].chosenTrump, "red");
  assert.deepEqual(
    played.trumpReveal.map((card) => card.id),
    ["bonus-stock", "red-stock"],
  );
  assert.equal(played.stock.length, 0);
  const out = trickFixture([
    [{ id: "out", type: "out" }],
    [{ id: "red", suit: "red", rank: 2 }],
  ]);
  assert.equal(playCard(out, 0, { cardId: "out" }).trump, null);
});
test("Wild Rage, Rage modifiers, and clean sweeps score correctly", () => {
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
  const sixteenWild = trickFixture([
    [{ id: "wild-16", type: "wild" }],
    [{ id: "red-15", suit: "red", rank: 15 }],
  ]);
  const sixteenPlayed = playCard(sixteenWild, 0, {
    cardId: "wild-16",
    declaredSuit: "red",
    declaredRank: 16,
  });
  assert.equal(playCard(sixteenPlayed, 1, { cardId: "red-15" }).lastWinner, 0);
  const bonus = trickFixture([
    [{ id: "bonus", type: "bonus" }],
    [{ id: "green", suit: "green", rank: 2 }],
  ]);
  const afterBonus = playCard(bonus, 0, { cardId: "bonus" });
  const scored = playCard(afterBonus, 1, { cardId: "green" });
  assert.equal(scored.phase, "roundSummary");
  assert.equal(scored.lastRoundScores?.[1], 1);
  const mad = trickFixture([
    [{ id: "mad", type: "mad" }],
    [{ id: "green", suit: "green", rank: 2 }],
  ]);
  const afterMad = playCard(mad, 0, { cardId: "mad" });
  const madScored = playCard(afterMad, 1, { cardId: "green" });
  assert.equal(madScored.players[1].roundBonus, -5);
  assert.equal(madScored.lastRoundScores?.[1], -9);
  const cleanSweep = {
    ...trickFixture([
      [{ id: "red-high", suit: "red", rank: 10 }],
      [{ id: "red-low", suit: "red", rank: 2 }],
    ]),
    cardsPerPlayer: 1,
  };
  const sweepAfterLead = playCard(cleanSweep, 0, { cardId: "red-high" });
  const sweepScored = playCard(sweepAfterLead, 1, { cardId: "red-low" });
  assert.equal(sweepScored.lastRoundScores?.[0], 1);
});
test("an all-action trick has no winner and leaves the lead in place", () => {
  const base = createGame({ seed: 88, playerCount: 4 });
  let state: GameState = {
    ...base,
    phase: "playing",
    currentPlayer: 0,
    trump: "blue",
    players: base.players.map((player, index) => ({
      ...player,
      hand: [["mad", "bonus", "change", "out"]][0]
        .map((type, cardIndex) =>
          cardIndex === index
            ? {
                id: `${type}-${index}`,
                type: type as "mad" | "bonus" | "change" | "out",
              }
            : null,
        )
        .filter(Boolean) as GameState["players"][number]["hand"],
      bid: 0,
      tricks: 0,
      roundBonus: 0,
    })),
    trick: [],
    leadSuit: null,
  };
  for (let playerId = 0; playerId < 4; playerId += 1)
    state = playCard(state, playerId, {
      cardId: ["mad-0", "bonus-1", "change-2", "out-3"][playerId],
    });
  assert.equal(state.lastWinner, null);
  assert.equal(state.currentPlayer, 0);
  assert.ok(state.players.every((player) => player.tricks === 0));
  assert.ok(state.players.every((player) => player.roundBonus === 0));
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
