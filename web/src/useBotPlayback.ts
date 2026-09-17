import { useEffect, useRef, useState } from "react";
import { isAbortError, loadSession, streamBotTurn } from "./api";
import type { GameState, GameStateCore, HistoryFrame } from "./types";

export interface BotActionFrame {
  frame: HistoryFrame;
  before: GameStateCore;
  number: number;
}

export function useBotPlayback() {
  const [action, setAction] = useState<BotActionFrame | null>(null);
  const [running, setRunning] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const skipRef = useRef(false);
  const release = useRef<(() => void) | null>(null);
  const latest = useRef<GameStateCore | null>(null);

  useEffect(
    () => () => {
      controller.current?.abort();
      release.current?.();
    },
    [],
  );

  function skip() {
    skipRef.current = true;
    setSkipping(true);
    release.current?.();
  }

  async function run(session: GameState, algorithm: string, budget: number) {
    if (controller.current) throw new Error("A bot turn is already running.");
    const abort = new AbortController();
    controller.current = abort;
    skipRef.current = false;
    latest.current = session;
    setSkipping(false);
    setRunning(true);
    setAction(null);
    let before: GameStateCore = session;
    let number = 0;
    try {
      try {
        return await streamBotTurn(
          session.sessionId,
          algorithm,
          budget,
          async (frame) => {
            if (abort.signal.aborted)
              throw new DOMException("Aborted", "AbortError");
            latest.current = frame.state;
            setAction({ frame, before, number: ++number });
            before = frame.state;
            // Readable pacing is independent of the bot's search budget. The stream
            // continues arriving while these presentation frames are displayed.
            if (!skipRef.current) {
              await new Promise<void>((resolve) => {
                const finish = () => {
                  window.clearTimeout(timer);
                  release.current = null;
                  resolve();
                };
                const timer = window.setTimeout(
                  finish,
                  frame.kind === "turn" ? 300 : 1000,
                );
                release.current = finish;
              });
            }
          },
          abort.signal,
        );
      } catch (error) {
        // The backend finishes a committed bot turn even if its viewer
        // disconnects, and persists it. If the stream broke mid-turn,
        // re-fetch: when the turn completed server-side, continue with the
        // fresh state instead of leaving a half-played turn stalled.
        if (!abort.signal.aborted && !isAbortError(error)) {
          try {
            const fresh = await loadSession(session.sessionId);
            latest.current = fresh;
            if (
              fresh.winner ||
              fresh.activePlayer !== "bot" ||
              fresh.turnNumber !== session.turnNumber
            ) {
              return fresh;
            }
          } catch {
            // The resume fetch failed too; surface the original stream error.
          }
        }
        throw error;
      }
    } finally {
      controller.current = null;
      if (!abort.signal.aborted) {
        setRunning(false);
        setAction(null);
      }
    }
  }

  return { action, running, skipping, run, skip, latest };
}
