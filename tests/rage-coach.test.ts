import assert from "node:assert/strict";
import test from "node:test";
import { reviewRound, type RoundPerformance } from "../lib/coach";

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
