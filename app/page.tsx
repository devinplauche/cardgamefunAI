"use client";

import { useMemo, useRef, useState } from "react";
import { SUITS, chooseBotBid, chooseBotPlay, continueGame, createGame, legalPlays, playCard, submitBid, type BotLevel, type GameState, type Suit } from "@/lib/rage";

const colors: Record<Suit, string> = { red: "#d85b51", orange: "#d99042", yellow: "#c6a631", green: "#57946d", blue: "#4e91a1", purple: "#8067ad" };
const botNames: Record<BotLevel, string> = { easy: "Easy", medium: "Medium", hard: "Hard" };
const botsFor = (count: number, level: BotLevel): BotLevel[] => Array.from({ length: count }, (_, index) => index === 0 ? "medium" : level);
const cardLabel = (card: { rank?: number; suit?: Suit; type?: string }) => card.type ? `${card.type.toUpperCase()} RAGE` : `${card.rank} · ${card.suit?.toUpperCase()}`;

export default function Home() {
  const [seed, setSeed] = useState(20260807); const [players, setPlayers] = useState(4); const [botLevel, setBotLevel] = useState<BotLevel>("medium");
  const [game, setGame] = useState<GameState>(() => createGame({ seed: 20260807, playerCount: 4, bots: botsFor(4, "medium") }));
  const [bid, setBid] = useState(2); const [selectedId, setSelectedId] = useState<string | null>(null); const [suitChoice, setSuitChoice] = useState<Suit>("red");
  const [busy, setBusy] = useState(false); const [winnerNotice, setWinnerNotice] = useState<string | null>(null); const timers = useRef<number[]>([]);
  const human = game.players[0]; const humanTurn = game.currentPlayer === 0; const legal = useMemo(() => new Set(legalPlays(game, 0).map((card) => card.id)), [game]); const selected = human.hand.find((card) => card.id === selectedId);
  const phaseLabel = game.phase === "bidding" ? "Bidding" : game.phase === "playing" ? "Playing" : game.phase === "roundSummary" ? "Round scored" : "Game over";
  const clearTimers = () => { timers.current.forEach(window.clearTimeout); timers.current = []; };
  const schedule = (task: () => void, delay: number) => { timers.current.push(window.setTimeout(task, delay)); };

  function runBots(start: GameState) {
    let current = start; setGame(current);
    const step = () => {
      if (current.phase === "gameOver" || current.phase === "roundSummary" || current.currentPlayer === 0) { setBusy(false); return; }
      setBusy(true); schedule(() => {
        const beforeTrick = current.trick.length;
        current = current.phase === "bidding" ? submitBid(current, current.currentPlayer, chooseBotBid(current, current.currentPlayer)) : playCard(current, current.currentPlayer, chooseBotPlay(current, current.currentPlayer));
        setGame(current);
        if (beforeTrick > 0 && current.trick.length === 0 && current.lastWinner !== null) {
          const winner = current.players[current.lastWinner]; setWinnerNotice(`${winner.name} takes the trick`); schedule(() => { setWinnerNotice(null); step(); }, 1400);
        } else schedule(step, current.phase === "bidding" ? 420 : 700);
      }, 450);
    };
    step();
  }
  function startGame() { clearTimers(); setBusy(false); setWinnerNotice(null); setBid(2); setSelectedId(null); setGame(createGame({ seed: seed || 1, playerCount: players, bots: botsFor(players, botLevel) })); }
  function placeBid() { if (humanTurn && game.phase === "bidding") runBots(submitBid(game, 0, bid)); }
  function playSelected() { if (!selected || !humanTurn || game.phase !== "playing") return; const next = playCard(game, 0, { cardId: selected.id, declaredSuit: selected.type === "wild" ? suitChoice : undefined, chosenTrump: selected.type === "change" ? suitChoice : undefined }); setSelectedId(null); if (next.trick.length === 0 && next.lastWinner !== null) { setGame(next); setWinnerNotice(`${next.players[next.lastWinner].name} takes the trick`); schedule(() => { setWinnerNotice(null); runBots(next); }, 1400); } else runBots(next); }
  function nextRound() { setBid(2); setSelectedId(null); runBots(continueGame(game)); }

  return <main className="rage-app">
    <header><div className="wordmark"><span>R</span> Rage table</div><div className="seed">Seed <b>{game.seed}</b></div></header>
    <section className="intro"><div><p className="kicker">COMPLETE MATCH · 2–6 PLAYERS</p><h1>Play the whole game.</h1><p>Ten descending rounds. Binding bids. Actual tricks. Actual scores.</p></div><button className="outline" onClick={startGame}>↻ New game</button></section>
    <section className={`setup-bar ${game.phase === "playing" ? "in-play" : ""}`} aria-label="Game setup"><label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><label>Players<select value={players} onChange={(event) => setPlayers(Number(event.target.value))}>{[2,3,4,5,6].map((count) => <option key={count}>{count}</option>)}</select></label><label>Opponent strength<select value={botLevel} onChange={(event) => setBotLevel(event.target.value as BotLevel)}>{(["easy", "medium", "hard"] as BotLevel[]).map((level) => <option key={level}>{botNames[level]}</option>)}</select></label><button onClick={startGame}>Deal this table</button></section>
    <section className="status"><div><span className="kicker">ROUND {game.round} OF 10</span><strong>{phaseLabel}</strong></div><div className="trump">Trump {game.trump ? <><i style={{ background: colors[game.trump] }} /> <b>{game.trump}</b></> : <b>out</b>}</div><div><span className="kicker">TO ACT</span><strong>{busy ? `${game.players[game.currentPlayer].name} is playing…` : game.players[game.currentPlayer].name}</strong></div></section>
    {game.phase === "bidding" && <section className="bid-preview"><div><span className="kicker">YOUR HAND · {human.hand.length} CARDS</span><h2>Read your hand before you bid</h2></div><div className="bid-hand">{human.hand.map((card) => <article className={`bid-card ${card.suit ?? "special"}`} key={card.id}><strong>{card.rank ?? "✦"}</strong><span>{cardLabel(card)}</span></article>)}</div></section>}
    <section className="table-grid">
      <aside className="scoreboard"><h2>Scoreboard</h2>{game.players.map((player) => <div className={`score-row ${player.id === game.currentPlayer ? "acting" : ""}`} key={player.id}><span><b>{player.name}</b><small>{player.id === 0 ? "You" : botNames[player.bot] + " bot"}</small></span><span className="bid-read">{player.bid ?? "–"}<small>bid</small></span><span className="trick-read">{player.tricks}<small>tricks</small></span><strong>{player.score}</strong></div>)}<p className="rules-note">Exact bid: +10 (+5 for exact zero). Each trick: +1. Bonus/Mad Rage modifies the trick winner.</p></aside>
      <section className="table"><div className="phase-tabs"><span className={game.phase === "bidding" ? "on" : ""}>1 Bid</span><span className={game.phase === "playing" ? "on" : ""}>2 Play</span><span className={game.phase === "roundSummary" || game.phase === "gameOver" ? "on" : ""}>3 Score</span></div>{game.phase === "bidding" ? <div className="bid-stage"><h2>Make your one bid</h2><p>Each bot will visibly bid after you commit.</p><div className="bid-picker"><button onClick={() => setBid(Math.max(0, bid - 1))}>−</button><strong>{bid}</strong><button onClick={() => setBid(Math.min(human.hand.length, bid + 1))}>+</button></div><button className="primary" disabled={!humanTurn || busy} onClick={placeBid}>Lock bid</button></div> : <><div className="trick-heading"><div><span className="kicker">CURRENT TRICK</span><h2>{game.leadSuit ? `Follow ${game.leadSuit}` : winnerNotice ?? "Leader chooses"}</h2></div><span>{game.trick.length}/{game.playerCount} cards</span></div><div className="trick-cards">{game.trick.map((played) => <article className="trick-card entering" key={`${played.player}-${played.card.id}`}><small>{game.players[played.player].name}</small><strong style={{ color: played.card.suit ? colors[played.card.suit] : "#443f48" }}>{played.card.rank ?? "✦"}</strong><span>{cardLabel(played.card)}</span></article>)}{Array.from({ length: Math.max(0, game.playerCount - game.trick.length) }, (_, index) => <article className="trick-card placeholder" key={index}><small>{game.players[(game.currentPlayer + index) % game.playerCount].name}</small><strong>{busy && index === 0 ? "…" : "?"}</strong><span>{busy && index === 0 ? "choosing" : "waiting"}</span></article>)}</div>{winnerNotice && <div className="winner-banner" role="status"><span>✦</span><strong>{winnerNotice}</strong><small>Leads the next trick</small></div>}{game.phase === "roundSummary" && <div className="summary"><h2>Round {game.round} scored</h2><p>{game.players.map((player, index) => `${player.name} ${game.lastRoundScores?.[index] ?? 0}`).join(" · ")}</p><button className="primary" onClick={nextRound}>Deal round {game.round + 1}</button></div>}{game.phase === "gameOver" && <div className="summary"><h2>{[...game.players].sort((a,b) => b.score - a.score)[0].name} wins</h2><p>Final score: {[...game.players].sort((a,b) => b.score - a.score).map((player) => `${player.name} ${player.score}`).join(" · ")}</p><button className="primary" onClick={startGame}>Play again</button></div>}</>}</section>
    </section>
    {game.phase === "playing" && <section className="hand"><div><span className="kicker">YOUR HAND · {human.hand.length} CARDS</span><h2>{humanTurn && !busy ? "Choose a legal card" : "Watch the table"}</h2></div>{selected?.type && (selected.type === "wild" || selected.type === "change") && <label className="suit-choice">Choose suit<select value={suitChoice} onChange={(event) => setSuitChoice(event.target.value as Suit)}>{SUITS.map((suit) => <option key={suit}>{suit}</option>)}</select></label>}<div className="hand-cards">{human.hand.map((card) => <button disabled={!humanTurn || busy || !legal.has(card.id)} onClick={() => setSelectedId(card.id)} className={`hand-card ${card.suit ?? "special"} ${selectedId === card.id ? "selected" : ""}`} key={card.id}><strong>{card.rank ?? "✦"}</strong><span>{cardLabel(card)}</span></button>)}</div><button className="primary play" disabled={!selected || !humanTurn || busy} onClick={playSelected}>Play selected card →</button></section>}
    <footer>Bot moves are shown one at a time · Every game is replayable by seed</footer>
  </main>;
}
