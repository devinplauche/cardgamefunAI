"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  SUITS,
  chooseBotBid,
  chooseBotPlay,
  chooseMctsBid,
  continueGame,
  createGame,
  finishTrick,
  legalPlays,
  playCard,
  submitBid,
  type BotLevel,
  type GameState,
  type PlayedCard,
  type Suit,
} from "@/lib/rage";

const colors: Record<Suit, string> = {
  red: "#d85b51",
  orange: "#d99042",
  yellow: "#c6a631",
  green: "#57946d",
  blue: "#4e91a1",
  purple: "#8067ad",
};
const botNames: Record<BotLevel, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
  extreme: "Extreme",
  inlaws: "In-laws — CHEATING",
  "absolute-inlaws": "Absolute In-laws — LEGAL CHEATS",
};
const botLevelFromSave = (level: unknown): BotLevel =>
  level === "easy" || level === "medium" || level === "hard" || level === "extreme" || level === "inlaws" || level === "absolute-inlaws"
    ? level
    : "medium";
const botLabel = (level: unknown) => botNames[botLevelFromSave(level)];
const botsFor = (count: number, level: BotLevel): BotLevel[] =>
  Array.from({ length: count }, (_, index) => (index === 0 ? "medium" : level));
const cardLabel = (card: { rank?: number; suit?: Suit; type?: string }) =>
  card.type
    ? `${card.type.toUpperCase()} RAGE`
    : `${card.rank} · ${card.suit?.toUpperCase()}`;
const cardFaceClass = (card: { suit?: Suit; type?: string }) =>
  `${card.suit ?? "special"} ${card.type ? `rage-${card.type}` : ""}`;
const playedLabel = (played: PlayedCard) =>
  played.card.type === "change"
    ? `CHANGE → ${played.chosenTrump?.toUpperCase()}`
    : played.card.type === "wild"
      ? `WILD ${played.declaredRank} → ${played.declaredSuit?.toUpperCase()}`
      : cardLabel(played.card);
const rageModifier = (trick: PlayedCard[]) =>
  trick.reduce(
    (total, played) =>
      total +
      (played.card.type === "bonus" ? 5 : played.card.type === "mad" ? -5 : 0),
    0,
  );
/**
 * Post-round bid coaching. Hitting a contract is worth +10 and missing costs -5,
 * so a missed bid is a ~15 point swing — by far the largest lever in the game.
 * The review runs the same search the Hard bot bids with, on the hand you held.
 */
type BidReview = {
  round: number;
  yourBid: number;
  suggested: number;
  tricks: number;
  /** 1-based trick on which the running count first passed the bid. */
  overshotAt: number | null;
};
const COACH_SIMULATIONS = 40;
const reviewLine = (review: BidReview) => {
  const { yourBid, suggested, tricks, overshotAt } = review;
  const cost = yourBid - tricks + 15;
  const agreed =
    suggested === yourBid
      ? "The search agrees with that bid."
      : `The search would have bid ${suggested}.`;
  if (tricks === yourBid)
    return `Bid ${yourBid}, took ${tricks} — exact. ${agreed}`;
  if (tricks > yourBid)
    return (
      `Bid ${yourBid}, took ${tricks} — ${tricks - yourBid} too many` +
      (overshotAt ? `, going past it on trick ${overshotAt}` : "") +
      `. ${agreed} Cost: ${cost} points versus an exact contract.`
    );
  return (
    `Bid ${yourBid}, took ${tricks} — ${yourBid - tricks} short. ${agreed} ` +
    `Cost: ${cost} points versus an exact contract.`
  );
};
type MatchResult = {
  id: string;
  playerName: string;
  playerScore: number;
  winnerName: string;
  winnerScore: number;
  playerCount: number;
  botLevel: string;
  playedAt: string;
};

export default function Home() {
  const [players, setPlayers] = useState(4);
  const [botLevel, setBotLevel] = useState<BotLevel>("medium");
  const [game, setGame] = useState<GameState>(() =>
    createGame({ seed: 20260807, playerCount: 4, bots: botsFor(4, "medium") }),
  );
  const [bid, setBid] = useState(2);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [suitChoice, setSuitChoice] = useState<Suit>("red");
  const [wildRank, setWildRank] = useState(16);
  const [newGameOpen, setNewGameOpen] = useState(false);
  const [playerName, setPlayerName] = useState("You");
  const [shareResults, setShareResults] = useState(false);
  const [matchHistory, setMatchHistory] = useState<MatchResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [bidReview, setBidReview] = useState<BidReview | null>(null);
  /** What the human bid this round, plus the search's answer on the same hand. */
  const pendingBid = useRef<{ round: number; yourBid: number; suggested: number } | null>(
    null,
  );
  /** The human's running trick total after each resolved trick this round. */
  const trickTrace = useRef<number[]>([]);
  const [winnerNotice, setWinnerNotice] = useState<string | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [saveStatus, setSaveStatus] = useState<
    "loading" | "saved" | "saving" | "offline"
  >("loading");
  const timers = useRef<number[]>([]);
  const recordedMatches = useRef(new Set<number>());
  useEffect(() => {
    let isCurrent = true;
    async function restoreOrDeal() {
      let restoredGame: GameState | null = null;
      try {
        const response = await fetch("/api/game", { cache: "no-store" });
        if (response.ok) {
          const saved = (await response.json()) as { game: GameState | null };
          restoredGame = saved.game;
        }
      } catch {
        // A fresh game is still playable if the save service is unavailable.
      }
      if (!isCurrent) return;
      if (restoredGame) {
        runBots(restoredGame);
      } else {
        const values = new Uint32Array(1);
        crypto.getRandomValues(values);
        const nextSeed = values[0] || 1;
        runBots(
          createGame({
            seed: nextSeed,
            playerCount: 4,
            bots: botsFor(4, "medium"),
          }),
        );
      }
      setStorageReady(true);
      setSaveStatus("saved");
    }
    void restoreOrDeal();
    return () => {
      isCurrent = false;
    };
    // runBots intentionally starts only this freshly dealt game on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if ("serviceWorker" in navigator)
      void navigator.serviceWorker.register("/sw.js");
  }, []);
  useEffect(() => {
    if (!storageReady) return;
    const saveTimer = window.setTimeout(async () => {
      setSaveStatus("saving");
      try {
        const response = await fetch("/api/game", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ game }),
        });
        setSaveStatus(response.ok ? "saved" : "offline");
      } catch {
        setSaveStatus("offline");
      }
    }, 700);
    return () => window.clearTimeout(saveTimer);
  }, [game, storageReady]);
  const loadMatchHistory = async () => {
    try {
      const response = await fetch("/api/matches", { cache: "no-store" });
      if (response.ok)
        setMatchHistory(
          ((await response.json()) as { matches: MatchResult[] }).matches,
        );
    } catch {
      // History is optional; the game remains playable offline.
    }
  };
  useEffect(() => {
    const historyTimer = window.setTimeout(() => {
      void loadMatchHistory();
    }, 0);
    return () => window.clearTimeout(historyTimer);
  }, []);
  useEffect(() => {
    if (
      game.phase !== "gameOver" ||
      !game.shareResults ||
      recordedMatches.current.has(game.seed)
    )
      return;
    recordedMatches.current.add(game.seed);
    const ordered = [...game.players].sort((a, b) => b.score - a.score);
    const winner = ordered[0];
    void fetch("/api/matches", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        playerName: game.players[0].name,
        playerScore: game.players[0].score,
        winnerName: winner.name,
        winnerScore: winner.score,
        playerCount: game.playerCount,
        botLevel,
      }),
    }).then(() => loadMatchHistory());
  }, [game, botLevel]);
  const human = game.players[0];
  const humanTurn = game.currentPlayer === 0;
  const legal = useMemo(
    () => new Set(legalPlays(game, 0).map((card) => card.id)),
    [game],
  );
  const selected = human.hand.find((card) => card.id === selectedId);
  const sortedHand = useMemo(
    () =>
      [...human.hand].sort((a, b) => {
        const suitDifference =
          (a.suit ? SUITS.indexOf(a.suit) : SUITS.length) -
          (b.suit ? SUITS.indexOf(b.suit) : SUITS.length);
        if (suitDifference) return suitDifference;
        const rankDifference =
          (a.rank ?? Number.MAX_SAFE_INTEGER) -
          (b.rank ?? Number.MAX_SAFE_INTEGER);
        if (rankDifference) return rankDifference;
        return (a.type ?? "").localeCompare(b.type ?? "");
      }),
    [human.hand],
  );
  const bidOrder = Array.from(
    { length: game.playerCount },
    (_, index) =>
      game.players[
        ((game.leader ?? (game.dealer + 1) % game.playerCount) + index) %
          game.playerCount
      ],
  );
  const bidLeader = bidOrder[0];
  const phaseLabel =
    game.phase === "bidding"
      ? "Bidding"
      : game.phase === "resolving"
        ? "Resolving trick"
        : game.phase === "playing"
          ? "Playing"
          : game.phase === "roundSummary"
            ? "Round scored"
            : "Game over";
  const clearTimers = () => {
    timers.current.forEach(window.clearTimeout);
    timers.current = [];
  };
  const schedule = (task: () => void, delay: number) => {
    timers.current.push(window.setTimeout(task, delay));
  };

  function reviewRound(state: GameState) {
    const pending = pendingBid.current;
    if (!pending || pending.round !== state.round) return;
    const tricks = state.players[0].tricks;
    const overshot = trickTrace.current.findIndex(
      (running) => running > pending.yourBid,
    );
    setBidReview({
      round: pending.round,
      yourBid: pending.yourBid,
      suggested: pending.suggested,
      tricks,
      overshotAt: overshot >= 0 ? overshot + 1 : null,
    });
    pendingBid.current = null;
  }
  function runBots(start: GameState) {
    let current = start;
    setGame(current);
    const step = () => {
      if (
        current.phase === "gameOver" ||
        current.phase === "roundSummary" ||
        (current.phase !== "resolving" && current.currentPlayer === 0)
      ) {
        if (current.phase === "gameOver" || current.phase === "roundSummary")
          reviewRound(current);
        setBusy(false);
        return;
      }
      setBusy(true);
      schedule(() => {
        if (current.phase === "resolving") {
          current = finishTrick(current);
          trickTrace.current.push(current.players[0].tricks);
          setGame(current);
          if (current.lastWinner === null) {
            setWinnerNotice("No one takes the all-action trick");
          } else {
            const winner = current.players[current.lastWinner];
            const modifier = rageModifier(current.lastTrick);
            setWinnerNotice(
              `${winner.name} takes the trick${modifier ? ` · Rage ${modifier > 0 ? "+" : ""}${modifier}` : ""}`,
            );
          }
          schedule(() => {
            setWinnerNotice(null);
            step();
          }, 1400);
          return;
        }
        current =
          current.phase === "bidding"
            ? submitBid(
                current,
                current.currentPlayer,
                chooseBotBid(current, current.currentPlayer),
              )
            : playCard(
                current,
                current.currentPlayer,
                chooseBotPlay(current, current.currentPlayer),
                true,
              );
        setGame(current);
        schedule(
          step,
          current.phase === "resolving"
            ? 1100
            : current.phase === "bidding"
              ? 420
              : 700,
        );
      }, 450);
    };
    step();
  }
  function openNewGame() {
    setPlayers(game.playerCount);
    const currentOpponents = game.players
      .slice(1)
      .map((player) => botLevelFromSave(player.bot));
    if (currentOpponents.every((level) => level === currentOpponents[0]))
      setBotLevel(currentOpponents[0]);
    setPlayerName(game.players[0].name);
    setShareResults(Boolean(game.shareResults));
    setNewGameOpen(true);
  }
  function startGame() {
    clearTimers();
    setBusy(false);
    setWinnerNotice(null);
    setBid(2);
    setSelectedId(null);
    setBidReview(null);
    pendingBid.current = null;
    trickTrace.current = [];
    const values = new Uint32Array(1);
    crypto.getRandomValues(values);
    const nextSeed = values[0] || 1;
    setNewGameOpen(false);
    runBots(
      createGame({
        seed: nextSeed,
        playerCount: players,
        bots: botsFor(players, botLevel),
        playerName: playerName.trim().slice(0, 24) || "You",
        shareResults,
      }),
    );
  }
  function placeBid() {
    if (!humanTurn || game.phase !== "bidding") return;
    // Run the search on the hand you actually held, before any card is played.
    // Kept out of the bidding UI on purpose — it is a review, not a hint.
    pendingBid.current = {
      round: game.round,
      yourBid: bid,
      suggested: chooseMctsBid(game, 0, { simulations: COACH_SIMULATIONS }),
    };
    trickTrace.current = [];
    setBidReview(null);
    runBots(submitBid(game, 0, bid));
  }
  function playSelected() {
    if (!selected || !humanTurn || game.phase !== "playing") return;
    const next = playCard(
      game,
      0,
      {
        cardId: selected.id,
        declaredSuit: selected.type === "wild" ? suitChoice : undefined,
        declaredRank: selected.type === "wild" ? wildRank : undefined,
      },
      true,
    );
    setSelectedId(null);
    runBots(next);
  }
  function nextRound() {
    setBid(2);
    setSelectedId(null);
    setBidReview(null);
    trickTrace.current = [];
    runBots(continueGame(game));
  }

  return (
    <main className="rage-app">
      <header>
        <div className="wordmark">
          <span>R</span> Rage table
        </div>
        <div className="seed">
          Seed <b>{game.seed}</b>
          <small className={`save-status ${saveStatus}`}>
            {saveStatus === "loading"
              ? "Loading save…"
              : saveStatus === "saving"
                ? "Saving…"
                : saveStatus === "saved"
                  ? "Saved"
                  : "Save offline"}
          </small>
        </div>
      </header>
      <section className="intro">
        <div>
          <p className="kicker">COMPLETE MATCH · 2–6 PLAYERS</p>
          <h1>Play the whole game.</h1>
          <p>
            Ten descending rounds. Binding bids. Actual tricks. Actual scores.
          </p>
        </div>
        <button className="outline" onClick={openNewGame}>
          ↻ New game
        </button>
      </section>
      {newGameOpen && (
        <div className="new-game-backdrop">
          <button
            className="new-game-dismiss"
            aria-label="Keep current game"
            onClick={() => setNewGameOpen(false)}
          />
          <section
            className="new-game-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-game-title"
          >
            <span className="kicker">NEW TABLE</span>
            <h2 id="new-game-title">Start a fresh game</h2>
            <p>This replaces your saved table with a newly shuffled game.</p>
            <label>
              Your name
              <input
                maxLength={24}
                value={playerName}
                onChange={(event) => setPlayerName(event.target.value)}
              />
            </label>
            <label>
              Players
              <select
                value={players}
                onChange={(event) => setPlayers(Number(event.target.value))}
              >
                {[2, 3, 4, 5, 6].map((count) => (
                  <option key={count}>{count}</option>
                ))}
              </select>
            </label>
            <label className="share-match">
              <input
                type="checkbox"
                checked={shareResults}
                onChange={(event) => setShareResults(event.target.checked)}
              />
              Share this finished match in the public history
            </label>
            <label>
              Opponent strength
              <select
                value={botLevel}
                onChange={(event) =>
                  setBotLevel(event.target.value as BotLevel)
                }
              >
                {(["easy", "medium", "hard", "extreme", "inlaws", "absolute-inlaws"] as BotLevel[]).map((level) => (
                  <option key={level}>{botNames[level]}</option>
                ))}
              </select>
            </label>
            <div className="dialog-actions">
              <button className="outline" onClick={() => setNewGameOpen(false)}>
                Keep current game
              </button>
              <button className="primary" onClick={startGame}>
                Start new game
              </button>
            </div>
          </section>
        </div>
      )}
      <section className="status">
        <div>
          <span className="kicker">ROUND {game.round} OF 10</span>
          <strong>{phaseLabel}</strong>
        </div>
        <div className="trump">
          Trump{" "}
          {game.trump ? (
            <>
              <i style={{ background: colors[game.trump] }} />{" "}
              <b>{game.trump}</b>
            </>
          ) : (
            <b>out</b>
          )}
          {(game.trumpReveal ?? []).length > 0 && (
            <span className="trump-reveal" aria-label="Trump deck reveal">
              {(game.trumpReveal ?? []).map((card) => (
                <i
                  className={`reveal-card ${cardFaceClass(card)}`}
                  key={card.id}
                  title={cardLabel(card)}
                >
                  {card.rank ?? "✦"}
                </i>
              ))}
            </span>
          )}
        </div>
        <div>
          <span className="kicker">TO ACT</span>
          <strong>
            {busy
              ? `${game.players[game.currentPlayer].name} is playing…`
              : game.players[game.currentPlayer].name}
          </strong>
        </div>
      </section>
      {game.players.some((player) => player.bot === "inlaws" || player.bot === "absolute-inlaws") && (
        <section className="cheat-warning" role="status">
          <strong>
            {game.players.some((player) => player.bot === "absolute-inlaws")
              ? "ABSOLUTE IN-LAWS: FULL FORESIGHT, LEGAL SCORING."
              : "IN-LAWS MODE: THEY CAN SEE EVERY HAND AND THE DECK."}
          </strong>
          <span>
            They are coordinating to make sure you do not win, including down-trades to dump tricks on you. Card swaps this
            round: {(game.inLawSwaps ?? []).reduce((sum, count) => sum + count, 0)}.
          </span>
        </section>
      )}
      {game.phase === "bidding" && (
        <section className="bid-preview">
          <div>
            <span className="kicker">
              YOUR HAND · {human.hand.length} CARDS
            </span>
            <h2>Read your hand before you bid</h2>
          </div>
          <div className="bid-hand">
            {sortedHand.map((card) => (
              <article
                className={`bid-card ${cardFaceClass(card)}`}
                key={card.id}
              >
                <strong>{card.rank ?? "✦"}</strong>
                <span>{cardLabel(card)}</span>
              </article>
            ))}
          </div>
        </section>
      )}
      <section className="table-grid">
        <aside className="scoreboard">
          <h2>Scoreboard</h2>
          {game.players.map((player) => (
            <div
              className={`score-row ${player.id === game.currentPlayer ? "acting" : ""}`}
              key={player.id}
            >
              <span>
                <b>{player.name}</b>
                <small>
                  {player.id === 0 ? "You" : `${botLabel(player.bot)} bot`}
                </small>
              </span>
              <span className="bid-read">
                {player.bid ?? "–"}
                <small>bid</small>
              </span>
              <span className="trick-read">
                {player.tricks}
                <small>tricks</small>
              </span>
              <span className="rage-read">
                {player.roundBonus === 0
                  ? "—"
                  : `${player.roundBonus > 0 ? "+" : ""}${player.roundBonus}`}
                <small>rage</small>
              </span>
              <strong>{player.score}</strong>
            </div>
          ))}
          <p className="rules-note" style={{ display: "none" }}>
            Exact bid: +10 (+5 for exact zero). Miss your bid: −5. Each trick:
            +1. Take every trick: +5. Bonus/Mad Rage modifies the trick winner.
          </p>
          <p className="rules-note">
            Exact bid: +10. Miss your bid: -5. Each trick: +1. Take every trick:
            +5. Bonus/Mad Rage modifies the trick winner.
          </p>
        </aside>
        <aside className="match-history">
          <div>
            <span className="kicker">OPT-IN</span>
            <h2>Recent matches</h2>
          </div>
          {matchHistory.length ? (
            matchHistory.map((match) => (
              <div className="match-row" key={match.id}>
                <span>
                  <b>{match.winnerName}</b> won
                  <small>
                    {match.playerName} {match.playerScore} · {match.playerCount}{" "}
                    players
                  </small>
                </span>
                <strong>{match.winnerScore}</strong>
              </div>
            ))
          ) : (
            <p>No shared matches yet.</p>
          )}
        </aside>
        <section className="table">
          <div className="phase-tabs">
            <span className={game.phase === "bidding" ? "on" : ""}>1 Bid</span>
            <span
              className={
                game.phase === "playing" || game.phase === "resolving"
                  ? "on"
                  : ""
              }
            >
              2 Play
            </span>
            <span
              className={
                game.phase === "roundSummary" || game.phase === "gameOver"
                  ? "on"
                  : ""
              }
            >
              3 Score
            </span>
          </div>
          {game.phase === "bidding" ? (
            <div className="bid-stage">
              <span className="kicker">BIDDING ORDER</span>
              <p className="bid-leader">{bidLeader.name} leads this round</p>
              <div className="bid-steps" aria-label="Bids so far">
                {bidOrder.map((player) => (
                  <div
                    className={`bid-step ${player.id === game.currentPlayer ? "acting" : ""} ${player.bid !== null ? "locked" : ""}`}
                    key={player.id}
                  >
                    <small>{player.name}</small>
                    <strong>
                      {player.bid !== null
                        ? player.bid
                        : player.id === game.currentPlayer
                          ? busy
                            ? "…"
                            : "?"
                          : "—"}
                    </strong>
                    <span>
                      {player.bid !== null
                        ? "bid"
                        : player.id === game.currentPlayer
                          ? "to bid"
                          : "waiting"}
                    </span>
                  </div>
                ))}
              </div>
              {humanTurn ? (
                <>
                  <h2>Make your one bid</h2>
                  <p>Previous bids are locked. Read the table, then commit.</p>
                  <div className="bid-picker">
                    <button onClick={() => setBid(Math.max(0, bid - 1))}>
                      −
                    </button>
                    <strong>{bid}</strong>
                    <button
                      onClick={() =>
                        setBid(Math.min(human.hand.length, bid + 1))
                      }
                    >
                      +
                    </button>
                  </div>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={placeBid}
                  >
                    Lock bid
                  </button>
                </>
              ) : (
                <div className="bid-wait" role="status">
                  <strong>
                    {game.players[game.currentPlayer].name} is bidding
                  </strong>
                  <span>Your hand stays visible while you wait.</span>
                </div>
              )}
            </div>
          ) : (
            <>
              <div className="trick-heading">
                <div>
                  <span className="kicker">CURRENT TRICK</span>
                  <h2>
                    {game.leadSuit
                      ? `Follow ${game.leadSuit}`
                      : (winnerNotice ?? "Leader chooses")}
                  </h2>
                </div>
                <span>
                  {game.trick.length}/{game.playerCount} cards
                </span>
              </div>
              <div className="trick-cards">
                {game.trick.map((played) => (
                  <article
                    className={`trick-card entering ${cardFaceClass(played.card)}`}
                    key={`${played.player}-${played.card.id}`}
                  >
                    <small>{game.players[played.player].name}</small>
                    <strong
                      style={{
                        color: played.card.suit
                          ? colors[played.card.suit]
                          : "#443f48",
                      }}
                    >
                      {played.card.rank ?? "✦"}
                    </strong>
                    <span>{playedLabel(played)}</span>
                  </article>
                ))}
                {Array.from(
                  { length: Math.max(0, game.playerCount - game.trick.length) },
                  (_, index) => (
                    <article className="trick-card placeholder" key={index}>
                      <small>
                        {
                          game.players[
                            (game.currentPlayer + index) % game.playerCount
                          ].name
                        }
                      </small>
                      <strong>{busy && index === 0 ? "…" : "?"}</strong>
                      <span>
                        {busy && index === 0 ? "choosing" : "waiting"}
                      </span>
                    </article>
                  ),
                )}
              </div>
              {winnerNotice && (
                <div className="winner-banner" role="status">
                  <span>✦</span>
                  <strong>{winnerNotice}</strong>
                  <small>
                    {game.lastWinner === null
                      ? `${game.players[game.currentPlayer].name} leads again`
                      : "Leads the next trick"}
                  </small>
                </div>
              )}
              {game.phase === "roundSummary" && (
                <div className="summary">
                  <h2>Round {game.round} scored</h2>
                  <p>
                    {game.players
                      .map(
                        (player, index) =>
                          `${player.name} ${game.lastRoundScores?.[index] ?? 0}`,
                      )
                      .join(" · ")}
                  </p>
                  {bidReview && bidReview.round === game.round && (
                    <p
                      className={`bid-review ${bidReview.tricks === bidReview.yourBid ? "exact" : "missed"}`}
                    >
                      {reviewLine(bidReview)}
                    </p>
                  )}
                  <button className="primary" onClick={nextRound}>
                    Deal round {game.round + 1}
                  </button>
                </div>
              )}
              {game.phase === "gameOver" && (
                <div className="summary">
                  <h2>
                    {
                      [...game.players].sort((a, b) => b.score - a.score)[0]
                        .name
                    }{" "}
                    wins
                  </h2>
                  <p>
                    Final score:{" "}
                    {[...game.players]
                      .sort((a, b) => b.score - a.score)
                      .map((player) => `${player.name} ${player.score}`)
                      .join(" · ")}
                  </p>
                  {bidReview && bidReview.round === game.round && (
                    <p
                      className={`bid-review ${bidReview.tricks === bidReview.yourBid ? "exact" : "missed"}`}
                    >
                      {reviewLine(bidReview)}
                    </p>
                  )}
                  <button className="primary" onClick={openNewGame}>
                    New game
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </section>
      {game.phase === "playing" && (
        <section className="hand">
          <div>
            <span className="kicker">
              YOUR HAND · {human.hand.length} CARDS
            </span>
            <h2>
              {humanTurn && !busy ? "Choose a legal card" : "Watch the table"}
            </h2>
          </div>
          {selected?.type === "wild" && (
            <div className="wild-choices">
              <label className="suit-choice">
                Wild suit
                <select
                  value={suitChoice}
                  onChange={(event) =>
                    setSuitChoice(event.target.value as Suit)
                  }
                >
                  {SUITS.map((suit) => (
                    <option key={suit}>{suit}</option>
                  ))}
                </select>
              </label>
              <label className="suit-choice">
                Wild number
                <select
                  value={wildRank}
                  onChange={(event) => setWildRank(Number(event.target.value))}
                >
                  {Array.from({ length: 17 }, (_, rank) => (
                    <option key={rank} value={rank}>
                      {rank}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <div className="hand-cards">
            {sortedHand.map((card) => (
              <button
                disabled={!humanTurn || busy || !legal.has(card.id)}
                onClick={() => setSelectedId(card.id)}
                className={`hand-card ${cardFaceClass(card)} ${selectedId === card.id ? "selected" : ""}`}
                key={card.id}
              >
                <strong>{card.rank ?? "✦"}</strong>
                <span>{cardLabel(card)}</span>
              </button>
            ))}
          </div>
          <button
            className="primary play"
            disabled={!selected || !humanTurn || busy}
            onClick={playSelected}
          >
            Play selected card →
          </button>
        </section>
      )}
      <footer>
        Bot moves are shown one at a time · Every game is replayable by seed
      </footer>
    </main>
  );
}
