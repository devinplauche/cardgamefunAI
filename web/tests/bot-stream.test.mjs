import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/botStream.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const { readBotStream, BotStreamError } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const encoder = new TextEncoder();
const state = { sessionId: "test", activePlayer: "player" };
const frame = { id: "1", label: "Played épée" };
const encode = (events) =>
  encoder.encode(events.map(JSON.stringify).join("\n") + "\n");
const stream = (chunks) =>
  new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(chunk));
      controller.close();
    },
  });

test("arbitrary chunk boundaries preserve UTF-8 and frame order", async () => {
  const bytes = encode([
    { type: "frame", frame },
    { type: "complete", state },
  ]);
  const frames = [];
  assert.deepEqual(
    await readBotStream(
      stream([...bytes].map((byte) => Uint8Array.of(byte))),
      async (f) => frames.push(f),
    ),
    state,
  );
  assert.deepEqual(frames, [frame]);
});

test("coalesced events await presentation before returning final state", async () => {
  const order = [];
  const bytes = encode([
    { type: "frame", frame },
    { type: "frame", frame: { ...frame, id: "2" } },
    { type: "complete", state },
  ]);
  await readBotStream(stream([bytes]), async (f) => {
    order.push(`start-${f.id}`);
    await new Promise((resolve) => setTimeout(resolve, 5));
    order.push(`end-${f.id}`);
  });
  assert.deepEqual(order, ["start-1", "end-1", "start-2", "end-2"]);
});

test("truncated connection cannot masquerade as a completed turn", async () => {
  await assert.rejects(
    readBotStream(stream([encode([{ type: "frame", frame }])]), async () => {}),
    /ended early/,
  );
});

test("server error preserves the authoritative recovery state", async () => {
  await assert.rejects(
    readBotStream(
      stream([encode([{ type: "error", error: "Search failed", state }])]),
      async () => {},
    ),
    (error) =>
      error instanceof BotStreamError &&
      error.message === "Search failed" &&
      error.state.sessionId === "test",
  );
});

test("malformed events fail rather than leave controls locked forever", async () => {
  await assert.rejects(
    readBotStream(stream([encoder.encode("not json\n")]), async () => {}),
    SyntaxError,
  );
});
