import assert from "node:assert/strict";
import test from "node:test";
import { assessDecision, reviewRound, type RoundPerformance } from "../lib/coach";

// A round where the player bid 3 and steered to it exactly.
const clean: RoundPerformance = {
  round: 1,
  bid: 3,
  suggestedBid: 3,
  tricks: 3,
  tricksInRound: 10,
  trickTrace: [0, 1, 1, 2, 2, 2, 3, 3, 3, 3],
  roundBonus: 0,
};
const withTrace = (
  overrides: Partial<RoundPerformance> & { trickTrace: number[] },
): RoundPerformance => ({
  ...clean,
  tricks: overrides.trickTrace[overrides.trickTrace.length - 1],
  ...overrides,
});

test("an exact contract earns the top grade and costs nothing", () => {
  const review = reviewRound(clean);
  assert.equal(review.contract, "exact");
  assert.equal(review.grade, "A");
  assert.equal(review.cost, 0);
  assert.equal(review.overshotAt, null);
});

test("bidding zero and taking zero is graded like any other exact contract", () => {
  const review = reviewRound(
    withTrace({ bid: 0, suggestedBid: 0, trickTrace: [0, 0, 0, 0] }),
  );
  assert.equal(review.contract, "exact");
  assert.equal(review.grade, "A");
  assert.equal(review.cost, 0);
});

test("overshooting names the trick where the count passed the bid", () => {
  const review = reviewRound(
    withTrace({ bid: 2, suggestedBid: 2, trickTrace: [0, 1, 2, 3, 3] }),
  );
  assert.equal(review.contract, "over");
  assert.equal(review.overshotAt, 4);
  // taking one more than the bid forfeits the +10 and takes the -5 instead
  assert.equal(review.cost, 2 - 3 + 15);
});

test("undershooting reports the shortfall with no overshoot trick", () => {
  const review = reviewRound(
    withTrace({ bid: 3, suggestedBid: 3, trickTrace: [0, 0, 1, 1] }),
  );
  assert.equal(review.contract, "under");
  assert.equal(review.overshotAt, null);
  assert.equal(review.cost, 3 - 1 + 15);
});

test("the grade degrades with the size of the miss", () => {
  const miss = (bid: number, tricks: number) =>
    reviewRound(
      withTrace({
        bid,
        suggestedBid: bid,
        trickTrace: Array.from({ length: 6 }, () => tricks),
        tricks,
      }),
    ).grade;
  assert.equal(miss(3, 3), "A");
  assert.equal(miss(3, 4), "B");
  assert.equal(miss(3, 5), "C");
  assert.equal(miss(3, 6), "D");
  assert.equal(miss(5, 1), "D");
});

test("a bid the search agreed with blames the play, not the read", () => {
  const review = reviewRound(
    withTrace({ bid: 3, suggestedBid: 3, trickTrace: [0, 1, 2, 3, 4] }),
  );
  assert.equal(review.bidRead, "sound");
  assert.match(review.notes.join(" "), /play|steer|shed|duck/i);
});

test("a hand bid below its worth is flagged as a misread", () => {
  const review = reviewRound(
    withTrace({ bid: 1, suggestedBid: 4, trickTrace: [1, 2, 3, 4] }),
  );
  assert.equal(review.bidRead, "low");
  assert.match(review.notes.join(" "), /4/);
});

test("a hand bid above its worth is flagged as a misread the other way", () => {
  const review = reviewRound(
    withTrace({ bid: 5, suggestedBid: 2, trickTrace: [0, 1, 2, 2] }),
  );
  assert.equal(review.bidRead, "high");
});

test("Rage modifiers are called out when they swing the round", () => {
  const stung = reviewRound(withTrace({ roundBonus: -5, trickTrace: [1, 2, 3] }));
  assert.match(stung.notes.join(" "), /mad/i);
  const gained = reviewRound(withTrace({ roundBonus: 5, trickTrace: [1, 2, 3] }));
  assert.match(gained.notes.join(" "), /bonus/i);
  const quiet = reviewRound(withTrace({ roundBonus: 0, trickTrace: [1, 2, 3] }));
  assert.ok(!/mad rage|bonus rage/i.test(quiet.notes.join(" ")));
});

test("a called clean sweep is recognised", () => {
  const review = reviewRound({
    round: 8,
    bid: 3,
    suggestedBid: 3,
    tricks: 3,
    tricksInRound: 3,
    trickTrace: [1, 2, 3],
    roundBonus: 0,
  });
  assert.equal(review.contract, "exact");
  assert.match(review.notes.join(" "), /sweep/i);
});

test("the headline always states the bid and what was taken", () => {
  for (const performance of [
    clean,
    withTrace({ bid: 2, suggestedBid: 2, trickTrace: [0, 1, 2, 3] }),
    withTrace({ bid: 4, suggestedBid: 1, trickTrace: [0, 1, 1, 1] }),
  ]) {
    const review = reviewRound(performance);
    assert.match(review.headline, new RegExp(`\\b${performance.bid}\\b`));
    assert.match(review.headline, new RegExp(`\\b${performance.tricks}\\b`));
  }
});

test("the review is pure and does not mutate its input", () => {
  const performance = withTrace({ bid: 2, suggestedBid: 3, trickTrace: [0, 1, 2, 3] });
  const snapshot = JSON.stringify(performance);
  const first = reviewRound(performance);
  const second = reviewRound(performance);
  assert.deepEqual(first, second);
  assert.equal(JSON.stringify(performance), snapshot);
});

test("an empty trick trace still produces a usable review", () => {
  const review = reviewRound({
    round: 10,
    bid: 0,
    suggestedBid: 0,
    tricks: 0,
    tricksInRound: 1,
    trickTrace: [],
    roundBonus: 0,
  });
  assert.equal(review.contract, "exact");
  assert.equal(review.overshotAt, null);
  assert.ok(review.headline.length > 0);
});

// --- play feedback ----------------------------------------------------------
// Fixture: blue is trump, red is led, and the trick is decided by the red 9
// unless the player beats it.
const red = (rank: number) => ({ id: `red-${rank}`, suit: "red" as const, rank });
const played = (player: number, rank: number) => ({ player, card: red(rank) });
/** p1 leads the red 9; seats 2 and 3 follow low. Seat 0's card decides it. */
const trickAround = (yours: number) => [
  played(1, 9),
  played(0, yours),
  played(2, 4),
  played(3, 6),
];

test("a single legal card is recorded as forced, not as a decision", () => {
  const decision = assessDecision({
    trick: 3,
    needed: 1,
    legal: [red(2)],
    played: red(2),
    resolved: trickAround(2),
    trump: "blue",
    playerId: 0,
  });
  assert.equal(decision.forced, true);
  assert.equal(decision.kind, "forced");
});

test("ducking a trick you needed, while holding a winner, is a missed trick", () => {
  const decision = assessDecision({
    trick: 4,
    needed: 1,
    legal: [red(2), red(15)],
    played: red(2),
    resolved: trickAround(2),
    trump: "blue",
    playerId: 0,
  });
  assert.equal(decision.wonTrick, false);
  assert.equal(decision.couldHaveWon, true);
  assert.equal(decision.kind, "missed-trick");
  assert.match(decision.betterCard ?? "", /15/);
});

test("taking a trick you did not need, with a safe card available, is a loose trick", () => {
  const decision = assessDecision({
    trick: 6,
    needed: 0,
    legal: [red(2), red(15)],
    played: red(15),
    resolved: trickAround(15),
    trump: "blue",
    playerId: 0,
  });
  assert.equal(decision.wonTrick, true);
  assert.equal(decision.couldHaveDucked, true);
  assert.equal(decision.kind, "loose-trick");
  assert.match(decision.betterCard ?? "", /2/);
});

test("winning a trick you needed is on plan", () => {
  const decision = assessDecision({
    trick: 2,
    needed: 2,
    legal: [red(2), red(15)],
    played: red(15),
    resolved: trickAround(15),
    trump: "blue",
    playerId: 0,
  });
  assert.equal(decision.kind, "on-plan");
});

test("losing a trick you needed with no winner in hand is unavoidable", () => {
  const decision = assessDecision({
    trick: 5,
    needed: 1,
    legal: [red(2), red(3)],
    played: red(3),
    resolved: trickAround(3),
    trump: "blue",
    playerId: 0,
  });
  assert.equal(decision.couldHaveWon, false);
  assert.equal(decision.kind, "unavoidable");
});

const decisionOf = (
  kind: "loose-trick" | "missed-trick" | "on-plan" | "forced",
  trick: number,
) => ({
  trick,
  kind,
  forced: kind === "forced",
  needed: kind === "missed-trick" ? 1 : 0,
  wonTrick: kind === "loose-trick",
  couldHaveWon: kind === "missed-trick",
  couldHaveDucked: kind === "loose-trick",
  card: "2 red",
  betterCard: kind === "on-plan" || kind === "forced" ? undefined : "15 red",
});

test("play feedback names the trick and the card that would have worked", () => {
  const review = reviewRound({
    ...clean,
    bid: 2,
    suggestedBid: 2,
    tricks: 3,
    trickTrace: [0, 1, 2, 3, 3],
    decisions: [decisionOf("on-plan", 1), decisionOf("loose-trick", 4)],
  });
  assert.equal(review.playVerdict, "leaked");
  assert.equal(review.leaks.length, 1);
  assert.equal(review.leaks[0].trick, 4);
  const text = review.notes.join(" ");
  assert.match(text, /trick 4/i);
  assert.match(text, /15 red/);
});

test("a round played to plan is reported as clean even when the bid was wrong", () => {
  const review = reviewRound({
    ...clean,
    bid: 1,
    suggestedBid: 4,
    tricks: 4,
    trickTrace: [1, 2, 3, 4],
    decisions: [decisionOf("on-plan", 1), decisionOf("forced", 2)],
  });
  assert.equal(review.playVerdict, "clean");
  assert.equal(review.leaks.length, 0);
});

// The audit found play advice was gated behind the search agreeing with the
// bid, so two thirds of missed rounds got no play feedback at all.
test("play feedback appears even when the bid itself was a misread", () => {
  const review = reviewRound({
    ...clean,
    bid: 1,
    suggestedBid: 5,
    tricks: 3,
    trickTrace: [1, 2, 3],
    decisions: [decisionOf("loose-trick", 2), decisionOf("loose-trick", 5)],
  });
  assert.equal(review.bidRead, "low");
  assert.equal(review.leaks.length, 2);
  assert.match(review.notes.join(" "), /trick 2/i);
});

test("a round with nothing but forced cards says so instead of blaming the play", () => {
  const review = reviewRound({
    ...clean,
    bid: 2,
    suggestedBid: 2,
    tricks: 3,
    trickTrace: [1, 2, 3],
    decisions: [decisionOf("forced", 1), decisionOf("forced", 2)],
  });
  assert.equal(review.playVerdict, "forced");
  assert.equal(review.leaks.length, 0);
});

test("omitting decisions keeps the older bid-only review working", () => {
  const review = reviewRound(clean);
  assert.equal(review.playVerdict, "unknown");
  assert.deepEqual(review.leaks, []);
});
