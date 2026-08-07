export const SUITS = [
  "red",
  "orange",
  "yellow",
  "green",
  "blue",
  "purple",
] as const;
export type Suit = (typeof SUITS)[number];
export type CardType = "wild" | "bonus" | "mad" | "change" | "out";
export type BotLevel = "easy" | "medium" | "hard";
export type Card = { id: string; suit?: Suit; rank?: number; type?: CardType };
export type PlayedCard = {
  player: number;
  card: Card;
  declaredSuit?: Suit;
  chosenTrump?: Suit;
};
export type Phase =
  | "bidding"
  | "playing"
  | "resolving"
  | "roundSummary"
  | "gameOver";
export type Player = {
  id: number;
  name: string;
  bot: BotLevel;
  hand: Card[];
  bid: number | null;
  tricks: number;
  score: number;
  roundBonus: number;
};
export type GameState = {
  seed: number;
  rng: number;
  playerCount: number;
  round: number;
  dealer: number;
  phase: Phase;
  players: Player[];
  trump: Suit | null;
  stock: Card[];
  trick: PlayedCard[];
  lastTrick: PlayedCard[];
  leadSuit: Suit | null;
  currentPlayer: number;
  lastWinner: number | null;
  lastRoundScores: number[] | null;
  log: string[];
};
export type Play = { cardId: string; declaredSuit?: Suit; chosenTrump?: Suit };

const next = (rng: number) => (rng * 1664525 + 1013904223) >>> 0;
const pick = <T>(items: T[], rng: number): [T, number] => {
  const updated = next(rng);
  return [items[updated % items.length], updated];
};
const advance = (state: GameState, from = state.currentPlayer) =>
  (from + 1) % state.playerCount;
const cloneCard = (card: Card) => ({ ...card });

export function cardName(card: Card) {
  return card.type
    ? `${card.type[0].toUpperCase()}${card.type.slice(1)} Rage`
    : `${card.rank} ${card.suit}`;
}

export function createDeck(): Card[] {
  const numbered = SUITS.flatMap((suit) =>
    Array.from({ length: 16 }, (_, rank) => ({
      id: `${suit}-${rank}`,
      suit,
      rank,
    })),
  );
  const specials: Card[] = ["wild", "bonus", "mad"].flatMap((type) =>
    Array.from({ length: 2 }, (_, i) => ({
      id: `${type}-${i}`,
      type: type as CardType,
    })),
  );
  const trumpChangers: Card[] = ["change", "out"].flatMap((type) =>
    Array.from({ length: 4 }, (_, i) => ({
      id: `${type}-${i}`,
      type: type as CardType,
    })),
  );
  return [...numbered, ...specials, ...trumpChangers];
}

function shuffle(cards: Card[], rng: number): [Card[], number] {
  const out = cards.map(cloneCard);
  let current = rng;
  for (let i = out.length - 1; i > 0; i -= 1) {
    current = next(current);
    const j = current % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return [out, current];
}

function dealRound(state: GameState): GameState {
  const cardsEach = 11 - state.round;
  const [deck, rng] = shuffle(createDeck(), state.rng);
  const players = state.players.map((player) => ({
    ...player,
    hand: [],
    bid: null,
    tricks: 0,
    roundBonus: 0,
  }));
  let cursor = 0;
  for (let card = 0; card < cardsEach; card += 1)
    for (let offset = 1; offset <= state.playerCount; offset += 1)
      players[advance(state, state.dealer + offset - 1)].hand.push(
        deck[cursor++],
      );
  let trump: Suit | null = null;
  while (cursor < deck.length && !trump) {
    const card = deck[cursor++];
    if (card.suit) trump = card.suit;
  }
  return {
    ...state,
    rng,
    players,
    stock: deck.slice(cursor),
    trump,
    trick: [],
    lastTrick: [],
    leadSuit: null,
    phase: "bidding",
    currentPlayer: advance(state, state.dealer),
    lastWinner: null,
    lastRoundScores: null,
    log: [
      ...state.log,
      `Round ${state.round}: ${cardsEach} cards, ${trump} trump`,
    ],
  };
}

export function createGame({
  seed = 1,
  playerCount = 4,
  bots = [],
}: { seed?: number; playerCount?: number; bots?: BotLevel[] } = {}): GameState {
  if (playerCount < 2 || playerCount > 6)
    throw new Error("Rage supports 2–6 players");
  const players = Array.from({ length: playerCount }, (_, id) => ({
    id,
    name: id === 0 ? "You" : ["Mia", "Ken", "Ari", "Zoe", "Sam"][id - 1],
    bot: bots[id] ?? (id === 0 ? "medium" : id % 3 === 0 ? "hard" : "medium"),
    hand: [],
    bid: null,
    tricks: 0,
    score: 0,
    roundBonus: 0,
  }));
  return dealRound({
    seed,
    rng: seed >>> 0 || 1,
    playerCount,
    round: 1,
    dealer: playerCount - 1,
    phase: "bidding",
    players,
    trump: null,
    stock: [],
    trick: [],
    lastTrick: [],
    leadSuit: null,
    currentPlayer: 0,
    lastWinner: null,
    lastRoundScores: null,
    log: [`Game seed ${seed}`],
  });
}

export function legalPlays(
  state: GameState,
  playerId = state.currentPlayer,
): Card[] {
  if (state.phase !== "playing" || playerId !== state.currentPlayer) return [];
  const hand = state.players[playerId].hand;
  if (!state.leadSuit) {
    if (state.trick.length === 0) return hand;
    const leadSetters = hand.filter((card) =>
      Boolean(card.suit || card.type === "wild"),
    );
    return leadSetters.length ? leadSetters : hand;
  }
  const followers = hand.filter((card) => card.suit === state.leadSuit);
  return followers.length ? followers : hand;
}

function establishLead(trick: PlayedCard[]) {
  for (const played of trick) {
    if (played.card.suit) return played.card.suit;
    if (played.card.type === "wild") return played.declaredSuit ?? null;
  }
  return null;
}

function effectiveSuit(played: PlayedCard) {
  return (
    played.card.suit ??
    (played.card.type === "wild" ? played.declaredSuit : undefined)
  );
}

function winsAgainst(
  challenger: PlayedCard,
  current: PlayedCard,
  lead: Suit | null,
  trump: Suit | null,
) {
  const challengerSuit = effectiveSuit(challenger);
  const currentSuit = effectiveSuit(current);
  if (!challengerSuit) return false;
  if (!currentSuit) return true;
  const challengerTrump = trump && challengerSuit === trump;
  const currentTrump = trump && currentSuit === trump;
  if (challengerTrump !== currentTrump) return Boolean(challengerTrump);
  if (challengerSuit !== currentSuit)
    return challengerSuit === lead && currentSuit !== lead;
  return (
    (challenger.card.type === "wild" ? 16 : (challenger.card.rank ?? -1)) >
    (current.card.type === "wild" ? 16 : (current.card.rank ?? -1))
  );
}

function resolveTrick(state: GameState): GameState {
  const leadSuit = establishLead(state.trick);
  let winner = state.trick[0];
  for (const challenger of state.trick.slice(1))
    if (winsAgainst(challenger, winner, leadSuit, state.trump))
      winner = challenger;
  const modifiers = state.trick.reduce(
    (sum, played) =>
      sum +
      (played.card.type === "bonus" ? 5 : played.card.type === "mad" ? -5 : 0),
    0,
  );
  const players = state.players.map((player) =>
    player.id === winner.player
      ? {
          ...player,
          tricks: player.tricks + 1,
          roundBonus: player.roundBonus + modifiers,
        }
      : player,
  );
  const base = {
    ...state,
    players,
    trick: [],
    lastTrick: state.trick,
    leadSuit: null,
    currentPlayer: winner.player,
    lastWinner: winner.player,
    log: [...state.log, `${state.players[winner.player].name} takes the trick`],
  };
  if (players.every((player) => player.hand.length === 0))
    return scoreRound(base);
  return base;
}

function scoreRound(state: GameState): GameState {
  const roundScores = state.players.map(
    (player) =>
      player.tricks +
      player.roundBonus +
      (player.tricks === player.bid ? (player.bid === 0 ? 5 : 10) : -5),
  );
  const players = state.players.map((player, index) => ({
    ...player,
    score: player.score + roundScores[index],
  }));
  const scored = {
    ...state,
    players,
    phase:
      state.round === 10 ? ("gameOver" as const) : ("roundSummary" as const),
    lastRoundScores: roundScores,
    log: [...state.log, `Round ${state.round} scored`],
  };
  return scored;
}

export function continueGame(state: GameState): GameState {
  if (state.phase !== "roundSummary") return state;
  return dealRound({
    ...state,
    round: state.round + 1,
    dealer: advance(state, state.dealer),
  });
}

export function submitBid(
  state: GameState,
  playerId: number,
  bid: number,
): GameState {
  if (state.phase !== "bidding" || playerId !== state.currentPlayer)
    throw new Error("Not this player’s bid");
  const max = state.players[playerId].hand.length;
  if (!Number.isInteger(bid) || bid < 0 || bid > max)
    throw new Error("Invalid bid");
  const players = state.players.map((player) =>
    player.id === playerId ? { ...player, bid } : player,
  );
  const allBids = players.every((player) => player.bid !== null);
  return {
    ...state,
    players,
    phase: allBids ? "playing" : "bidding",
    currentPlayer: allBids ? advance(state, state.dealer) : advance(state),
    log: [...state.log, `${state.players[playerId].name} bids ${bid}`],
  };
}

export function playCard(
  state: GameState,
  playerId: number,
  play: Play,
  deferResolution = false,
): GameState {
  if (state.phase !== "playing" || playerId !== state.currentPlayer)
    throw new Error("Not this player’s turn");
  const card = state.players[playerId].hand.find(
    (candidate) => candidate.id === play.cardId,
  );
  if (!card) throw new Error("Card is not in hand");
  if (!legalPlays(state).some((candidate) => candidate.id === card.id))
    throw new Error("Must follow suit");
  if (card.type === "wild" && !play.declaredSuit)
    throw new Error("Wild Rage needs a declared suit");
  if (card.type === "change" && !play.chosenTrump)
    throw new Error("Change Rage needs a new trump");
  const trick = [
    ...state.trick,
    {
      player: playerId,
      card,
      declaredSuit: play.declaredSuit,
      chosenTrump: play.chosenTrump,
    },
  ];
  const players = state.players.map((player) =>
    player.id === playerId
      ? {
          ...player,
          hand: player.hand.filter((candidate) => candidate.id !== card.id),
        }
      : player,
  );
  const trump =
    card.type === "change"
      ? play.chosenTrump!
      : card.type === "out"
        ? null
        : state.trump;
  const played = {
    ...state,
    players,
    trick,
    trump,
    leadSuit: establishLead(trick),
    currentPlayer: advance(state),
    log: [
      ...state.log,
      `${state.players[playerId].name} plays ${cardName(card)}`,
    ],
  };
  return trick.length === state.playerCount
    ? deferResolution
      ? { ...played, phase: "resolving" }
      : resolveTrick(played)
    : played;
}

export function finishTrick(state: GameState): GameState {
  if (state.phase !== "resolving")
    throw new Error("No trick is ready to resolve");
  return resolveTrick({ ...state, phase: "playing" });
}

function handValue(hand: Card[], trump: Suit | null) {
  return hand.reduce(
    (value, card) =>
      value +
      (card.type === "wild"
        ? 1.5
        : card.suit === trump && (card.rank ?? 0) >= 9
          ? 1
          : (card.rank ?? 0) >= 13
            ? 0.75
            : 0),
    0,
  );
}
export function chooseBotBid(state: GameState, playerId: number): number {
  return Math.max(
    0,
    Math.min(
      state.players[playerId].hand.length,
      Math.round(handValue(state.players[playerId].hand, state.trump)),
    ),
  );
}

export function chooseBotPlay(state: GameState, playerId: number): Play {
  const legal = legalPlays(state, playerId);
  const player = state.players[playerId];
  if (!legal.length) throw new Error("No legal bot move");
  let card: Card;
  let rng = state.rng;
  if (player.bot === "easy") [card, rng] = pick(legal, rng);
  else {
    const needs = (player.bid ?? 0) - player.tricks;
    const score = (candidate: Card) =>
      (candidate.type === "wild"
        ? 40
        : candidate.suit === state.trump
          ? 25
          : 0) + (candidate.rank ?? 0);
    const sorted = [...legal].sort((a, b) => score(a) - score(b));
    card = needs > 0 ? sorted[sorted.length - 1] : sorted[0];
    if (player.bot === "hard" && state.trick.length) {
      const contenders = [...sorted].sort(
        (a, b) => Math.abs(score(a) - 16) - Math.abs(score(b) - 16),
      );
      card = needs > 0 ? contenders[contenders.length - 1] : contenders[0];
    }
  }
  void rng;
  const preferredTrump = [...SUITS].sort(
    (a, b) =>
      player.hand.filter((candidate) => candidate.suit === b).length -
      player.hand.filter((candidate) => candidate.suit === a).length,
  )[0];
  return {
    cardId: card.id,
    declaredSuit:
      card.type === "wild" ? (state.trump ?? preferredTrump) : undefined,
    chosenTrump: card.type === "change" ? preferredTrump : undefined,
  };
}

export function advanceBots(state: GameState, humanPlayer = 0): GameState {
  let current = state;
  let guard = 0;
  while (
    current.phase !== "gameOver" &&
    current.phase !== "roundSummary" &&
    (current.phase === "resolving" || current.currentPlayer !== humanPlayer) &&
    guard++ < 5000
  ) {
    current =
      current.phase === "resolving"
        ? finishTrick(current)
        : current.phase === "bidding"
          ? submitBid(
              current,
              current.currentPlayer,
              chooseBotBid(current, current.currentPlayer),
            )
          : playCard(
              current,
              current.currentPlayer,
              chooseBotPlay(current, current.currentPlayer),
            );
  }
  if (guard >= 5000) throw new Error("Bot loop stalled");
  return current;
}

export function simulateGame(
  seed: number,
  playerCount: number,
  bots: BotLevel[] = Array.from({ length: playerCount }, () => "medium"),
): GameState {
  let state = createGame({ seed, playerCount, bots });
  let guard = 0;
  while (state.phase !== "gameOver" && guard++ < 20000) {
    if (state.phase === "roundSummary") state = continueGame(state);
    else if (state.phase === "resolving") state = finishTrick(state);
    else if (state.phase === "bidding")
      state = submitBid(
        state,
        state.currentPlayer,
        chooseBotBid(state, state.currentPlayer),
      );
    else
      state = playCard(
        state,
        state.currentPlayer,
        chooseBotPlay(state, state.currentPlayer),
      );
  }
  if (guard >= 20000) throw new Error("Simulation stalled");
  return state;
}
