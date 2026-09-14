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

/** Network chunks need not line up with events or UTF-8 characters. */
export async function readBotStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: HistoryFrame) => Promise<void>,
): Promise<GameState> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result: GameState | undefined;
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
    while (true) {
      const { value, done } = await reader.read();
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
    if (!result) throw new Error("Bot turn connection ended early.");
    return result;
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
