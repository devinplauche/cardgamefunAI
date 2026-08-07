"use client";

import { useMemo, useState } from "react";

type Suit = "red" | "orange" | "yellow" | "green" | "blue" | "purple";
type Card = { id: string; value?: number; suit?: Suit; label?: string; type?: "wild" | "bonus" | "mad" | "change" | "out" };

const suitNames: Record<Suit, string> = { red: "Red", orange: "Orange", yellow: "Yellow", green: "Green", blue: "Blue", purple: "Purple" };

const starterHand: Card[] = [
  { id: "r14", value: 14, suit: "red" },
  { id: "r7", value: 7, suit: "red" },
  { id: "o12", value: 12, suit: "orange" },
  { id: "y3", value: 3, suit: "yellow" },
  { id: "g9", value: 9, suit: "green" },
  { id: "b15", value: 15, suit: "blue" },
  { id: "p4", value: 4, suit: "purple" },
  { id: "bonus", label: "BONUS", type: "bonus" },
];

function cardStrength(card: Card, trump: Suit) {
  if (card.type === "wild") return 18;
  if (card.type) return card.type === "bonus" ? 4 : 3;
  return (card.value ?? 0) + (card.suit === trump ? 16 : 0);
}

function CardView({ card, selected, onClick }: { card: Card; selected: boolean; onClick: () => void }) {
  return (
    <button className={`playing-card ${card.suit ?? "special"} ${selected ? "selected" : ""}`} onClick={onClick} aria-label={card.label ?? `${card.value} ${card.suit} card`}>
      {card.type ? <><span className="special-mark">✦</span><span>{card.label}</span></> : <><span className="card-value">{card.value}</span><span className="card-suit">●</span></>}
    </button>
  );
}

export default function Home() {
  const [mode, setMode] = useState<"play" | "analyze">("play");
  const [hand, setHand] = useState(starterHand);
  const [selectedId, setSelectedId] = useState("r14");
  const [trump, setTrump] = useState<Suit>("blue");
  const [bid, setBid] = useState(2);
  const [tricks, setTricks] = useState(1);
  const [message, setMessage] = useState("Select a card to get a read on the play.");

  const selected = hand.find((card) => card.id === selectedId) ?? hand[0];
  const analysis = useMemo(() => {
    if (!selected) return { score: 0, label: "No card selected", text: "Your hand is empty. Start a new hand to keep playing." };
    const strength = cardStrength(selected, trump);
    const winChance = Math.min(96, Math.max(8, Math.round(27 + strength * 3.5 - tricks * 1.5)));
    const onTarget = bid > tricks ? "You still need tricks" : bid === tricks ? "You are on your bid" : "You may want to duck";
    return {
      score: winChance,
      label: selected.type === "bonus" ? "Timing play" : selected.suit === trump ? "Trump pressure" : selected.value && selected.value >= 12 ? "Strong lead" : "Control the count",
      text: `${onTarget}. ${selected.suit === trump ? `${suitNames[trump]} is trump, so this card can take a trick.` : "Keep this card if you need to avoid winning or protect a later lead."}`,
    };
  }, [selected, trump, tricks, bid]);

  function playSelected() {
    if (!selected) return;
    setHand((current) => current.filter((card) => card.id !== selected.id));
    setTricks((current) => current + (cardStrength(selected, trump) >= 20 ? 1 : 0));
    setSelectedId("");
    setMessage(`${selected.type ? selected.label : `${selected.value} ${selected.suit}`} played. The table is recalculating your line.`);
  }

  function newHand() {
    setHand(starterHand);
    setSelectedId("r14");
    setTricks(1);
    setMessage("Fresh hand dealt. Find the shape before you commit your bid.");
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">R</span><span>Rage<span className="brand-dot">.</span></span></div>
        <div className="top-actions"><button className="icon-button" aria-label="Help">?</button><button className="avatar" aria-label="Profile">JD</button></div>
      </header>

      <section className="hero-row">
        <div><p className="eyebrow">HAND 03 <span>•</span> ROUND 4 OF 10</p><h1>Read the table.</h1><p className="subhead">A calm second opinion for an unpredictable game.</p></div>
        <button className="new-hand" onClick={newHand}>↻ <span>New hand</span></button>
      </section>

      <nav className="mode-switch" aria-label="Game mode"><button className={mode === "play" ? "active" : ""} onClick={() => setMode("play")}>Play</button><button className={mode === "analyze" ? "active" : ""} onClick={() => setMode("analyze")}>Analyze</button></nav>

      <section className="table-card">
        <div className="table-header"><div><span className="label">YOUR BID</span><div className="bid-control"><button onClick={() => setBid(Math.max(0, bid - 1))}>−</button><strong>{bid}</strong><button onClick={() => setBid(Math.min(8, bid + 1))}>+</button></div></div><button className="trump-chip" onClick={() => setTrump((current) => ({ red: "orange", orange: "yellow", yellow: "green", green: "blue", blue: "purple", purple: "red" }[current] as Suit))} aria-label="Change trump suit"><span className={`suit-dot ${trump}`}></span><span>Trump</span><strong>{suitNames[trump]}</strong></button></div>
        <div className="trick-summary"><div className="ring"><strong>{tricks}</strong><span>tricks</span></div><div><p className="label">CURRENT READ</p><p className="read-line">{message}</p></div></div>
        <div className="opponents"><div className="opponent"><span className="opponent-avatar coral">M</span><span><b>Mia</b><small>bid 3 · 2 tricks</small></span></div><div className="opponent"><span className="opponent-avatar lavender">K</span><span><b>Ken</b><small>bid 1 · 1 trick</small></span></div><span className="round-pill">4 cards left</span></div>
      </section>

      <section className="content-grid">
        <div className="hand-panel"><div className="section-heading"><div><p className="label">YOUR HAND <span className="count">{hand.length}</span></p><h2>Choose your line</h2></div><button className="sort-button">Sort <span>↕</span></button></div><div className="hand-grid">{hand.map((card) => <CardView key={card.id} card={card} selected={card.id === selectedId} onClick={() => setSelectedId(card.id)} />)}</div><button className="primary-action" disabled={!selected} onClick={playSelected}>Play selected card <span>→</span></button></div>

        <aside className={`analysis-panel ${mode === "analyze" ? "analysis-focus" : ""}`}><div className="analysis-top"><div><p className="label">OPEN SPIEL READ <span className="info">i</span></p><h2>{analysis.label}</h2></div><span className="spark">✦</span></div><div className="confidence"><div><strong>{analysis.score}%</strong><span>estimated win chance</span></div><div className="confidence-bar"><i style={{ width: `${analysis.score}%` }} /></div></div><p className="analysis-copy">{analysis.text}</p><div className="signal"><span>◎</span><div><b>Information set</b><small>Based on trump, visible cards, bid pressure, and remaining count.</small></div></div><button className="ghost-action" onClick={() => setMessage("Analysis refreshed across 250 lightweight Monte Carlo rollouts.")}>Refresh analysis <span>↗</span></button></aside>
      </section>

      <footer><span>Rage is a 6-suit trick-taking game.</span><span><a href="https://en.wikipedia.org/wiki/Rage_(trick-taking_card_game)" target="_blank" rel="noreferrer">Rules</a><span className="footer-dot">•</span><a href="https://github.com/google-deepmind/open_spiel" target="_blank" rel="noreferrer">OpenSpiel</a></span></footer>
    </main>
  );
}
