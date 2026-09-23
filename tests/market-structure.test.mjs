import test from "node:test";
import assert from "node:assert/strict";
import { detectMarketStructure, detectSwings } from "../lib/market-structure.ts";

const seconds = 3600;
function candles() {
  const start = Math.floor(Date.now() / 3600000) * 3600 - 70 * seconds;
  const rows = Array.from({ length: 65 }, (_, i) => ({
    time: start + i * seconds, open: 101.6, high: 102, low: 101.4, close: 101.7, volume: 10,
  }));
  Object.assign(rows[48], { high: 100.4, low: 100, close: 100.3 });
  Object.assign(rows[50], { low: 101, high: 102, close: 101.7 });
  Object.assign(rows[52], { high: 100.6, low: 100.55, close: 100.58 });
  Object.assign(rows[54], { low: 101.2, high: 102, close: 101.7 });
  Object.assign(rows[58], { low: 100.65, high: 102, close: 101.7 });
  return rows;
}

test("overlapping unfilled gaps and confirmed swing low form a visible confluence", () => {
  const structure = detectMarketStructure(candles(), seconds, .8, 101.8, "crypto");
  const first = structure.gaps.find(g => g.formedIndex === 50 && g.kind === "fvg");
  const second = structure.gaps.find(g => g.formedIndex === 54 && g.kind === "fvg");
  assert.ok(first && second);
  assert.ok(first.overlapCount >= 2);
  assert.ok(second.overlapCount >= 2);
  assert.ok(first.fillPercent > 0 && first.fillPercent < 100);
  assert.equal(second.swing?.kind, "low");
  assert.equal(second.swing?.index, 58);
});

test("a fully filled gap no longer counts as active", () => {
  const rows = candles();
  rows[61].low = 99;
  const structure = detectMarketStructure(rows, seconds, .8, 101.8, "crypto");
  assert.equal(structure.gaps.some(g => g.formedIndex === 50 || g.formedIndex === 54), false);
});

test("missing buckets do not create a three-candle gap", () => {
  const rows = candles();
  for (let i = 50; i < rows.length; i++) rows[i].time += seconds;
  const structure = detectMarketStructure(rows, seconds, .8, 101.8, "crypto");
  assert.equal(structure.gaps.some(g => g.formedIndex === 50), false);
});

test("the newest high is not a confirmed swing", () => {
  const rows = candles();
  rows.at(-1).high = 108;
  assert.equal(detectSwings(rows).some(s => s.index === rows.length - 1), false);
});
