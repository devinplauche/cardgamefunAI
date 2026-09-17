import type { GameState, HistoryFrame } from "./types";

type BotEvent =
  | { type: "frame"; frame: HistoryFrame }
  | { type: "complete"; state: GameState }
  | { type: "error"; error: string; state: GameState };

export class BotStreamError extends Error {
  constructor(
    message: string,
    public state?: GameState,
  ) {
    super(message);
  }
}

/** The stream broke at the transport level (dropped connection, stall). */
export class BotStreamNetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BotStreamNetworkError";
  }
}

export interface ReadBotStreamOptions {
  /**
   * Abort the read when no chunk arrives for this long. A stalled stream
   * must surface as an error (so the caller can resume) rather than hang.
   */
  idleTimeoutMs?: number;
}

/** Network chunks need not line up with events or UTF-8 characters. */
export async function readBotStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: HistoryFrame) => Promise<void>,
  opts?: ReadBotStreamOptions,
): Promise<GameState> {
  const idleTimeoutMs = opts?.idleTimeoutMs ?? 120_000;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result: GameState | undefined;
  // A stall mid-turn aborts the read so the caller can re-fetch and resume
  // instead of leaving a half-played turn stalled forever. Note: cancel()
  // fulfills a pending read() with done:true rather than rejecting it, so
  // the stall is tracked with a flag instead of relying on the cancel reason.
  let idleTimer: number | undefined;
  let stalled = false;
  const poke = () => {
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(() => {
      stalled = true;
      reader.cancel().catch(() => undefined);
    }, idleTimeoutMs);
  };
  async function consume(line: string) {
    if (!line.trim()) return;
    if (result) throw new Error("Unexpected event after bot turn completion.");
    const event = JSON.parse(line) as BotEvent;
    if (event.type === "frame") await onFrame(event.frame);
    else if (event.type === "complete") result = event.state;
    else if (event.type === "error")
      throw new BotStreamError(event.error, event.state);
    else throw new Error("Unknown bot turn event.");
  }
  try {
    poke();
    while (true) {
      let read: ReadableStreamReadResult<Uint8Array>;
      try {
        read = await reader.read();
      } catch (error) {
        if (error instanceof BotStreamNetworkError) throw error;
        throw new BotStreamNetworkError(
          error instanceof Error ? error.message : "The bot turn connection broke.",
        );
      }
      poke();
      const { value, done } = read;
      pending += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf("\n")) !== -1) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        await consume(line);
      }
      if (done) break;
    }
    if (pending.trim()) await consume(pending);
    if (!result)
      throw new BotStreamNetworkError(
        stalled
          ? "The bot turn stalled. Check your connection and try again."
          : "The bot turn connection ended early.",
      );
    return result;
  } finally {
    window.clearTimeout(idleTimer);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
