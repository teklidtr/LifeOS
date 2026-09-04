import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { PERSONAL_MODEL_ACTION_LABELS } from "../src/personal-model.js";

test("Personal Model lifecycle actions expose descriptive screen-reader labels", () => {
  assert.match(PERSONAL_MODEL_ACTION_LABELS.track.ariaLabel, /working hypothesis.*seed proposal/i);
  assert.match(PERSONAL_MODEL_ACTION_LABELS.adopt.ariaLabel, /Preview adopting/i);
  assert.match(PERSONAL_MODEL_ACTION_LABELS.revise.ariaLabel, /Preview a revision/i);
  assert.match(PERSONAL_MODEL_ACTION_LABELS.contest.ariaLabel, /Preview marking.*needing review/i);
  assert.match(PERSONAL_MODEL_ACTION_LABELS.archive.ariaLabel, /Preview archiving/i);
});

test("Personal Model view keeps live status and tab semantics in the Obsidian renderer", async () => {
  const source = await readFile(
    new URL("../../src/personal-model-obsidian-view.ts", import.meta.url),
    "utf8",
  );
  assert.match(source, /aria-live/);
  assert.match(source, /role", "tablist"/);
  assert.match(source, /role", "tab"/);
  assert.match(source, /aria-label.*evidence/i);
});

test("Personal Model styles scale with user text size and collapse to one column", async () => {
  const styles = await readFile(new URL("../../styles.css", import.meta.url), "utf8");
  const start = styles.indexOf(".lifeos-personal-model {");
  assert.notEqual(start, -1);
  const personalModelStyles = styles.slice(start);

  assert.match(personalModelStyles, /font-size:\s*1rem/);
  assert.match(personalModelStyles, /font:\s*inherit/);
  assert.match(personalModelStyles, /min-height:\s*2\.75rem/);
  assert.match(personalModelStyles, /@container lifeos-personal-model \(max-width:\s*48rem\)/);
  assert.doesNotMatch(personalModelStyles, /font-size:\s*\d+(?:\.\d+)?px/);
});
