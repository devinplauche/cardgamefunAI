import assert from "node:assert/strict";
import test from "node:test";
import { BOT_LEVEL_OPTIONS } from "../lib/bot-levels";

test("bot selector values stay aligned with their internal levels", () => {
  const extreme = BOT_LEVEL_OPTIONS.find((option) => option.label === "Extreme");
  assert.deepEqual(extreme, { value: "extreme", label: "Extreme" });
  assert.deepEqual(
    BOT_LEVEL_OPTIONS.map((option) => option.value),
    ["easy", "medium", "hard", "extreme", "inlaws", "absolute-inlaws"],
  );
});
