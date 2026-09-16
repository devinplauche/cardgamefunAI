/// <reference types="vite/client" />
import { useState } from "react";
import { CARD_ART } from "./cardArt";
import type { CardView } from "./types";

/** Decorative artwork: the adjacent card name and rules remain accessible. */
export function CardArtwork({
  card,
  compact = false,
  tapped = false,
}: {
  card: Pick<CardView, 'name' | 'cardType'>;
  compact?: boolean;
  /** Expended champions render turned sideways, like a tapped card. */
  tapped?: boolean;
}) {
  const filename = CARD_ART[card.name];
  const [failedSource, setFailedSource] = useState<string>();
  const src = filename
    ? `${import.meta.env.BASE_URL}cards/${filename}`
    : undefined;
  const available = src && failedSource !== src;

  return (
    <div
      className={`card-artwork${compact ? " compact" : ""}${tapped ? " tapped" : ""}`}
      aria-hidden="true"
    >
      <span className="artwork-fallback">
        {card.cardType === "champion" ? "♜" : "✦"}
      </span>
      {available ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailedSource(src)}
        />
      ) : null}
    </div>
  );
}
