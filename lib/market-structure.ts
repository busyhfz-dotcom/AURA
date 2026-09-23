import type { Candle } from "./analysis";

export type Swing = {
  kind: "high" | "low";
  price: number;
  time: number;
  index: number;
};

export type GapZone = {
  kind: "fvg" | "candle";
  direction: "bullish" | "bearish";
  lower: number;
  upper: number;
  formedAt: number;
  formedIndex: number;
  fillPercent: number;
  overlapCount: number;
  overlapLower?: number;
  overlapUpper?: number;
  swing?: Swing;
  distance: number;
};

export type MarketStructure = {
  gaps: GapZone[];
  activeGapCount: number;
  swings: Swing[];
  latestHigh?: Swing;
  latestLow?: Swing;
  focus?: GapZone;
};

const intervalDistance = (level: number, lower: number, upper: number) =>
  Math.max(lower - level, 0, level - upper);

/** Pivots need three completed candles on both sides, so the newest three cannot repaint a swing. */
export function detectSwings(candles: Candle[], width = 3): Swing[] {
  const swings: Swing[] = [];
  for (let i = width; i < candles.length - width; i++) {
    const neighbours = candles.slice(i - width, i + width + 1).filter((_, j) => j !== width);
    if (neighbours.every(c => candles[i].high > c.high))
      swings.push({ kind: "high", price: candles[i].high, time: candles[i].time, index: i });
    if (neighbours.every(c => candles[i].low < c.low))
      swings.push({ kind: "low", price: candles[i].low, time: candles[i].time, index: i });
  }
  return swings;
}

export function detectMarketStructure(
  candles: Candle[], seconds: number, atr: number, price: number, market: "crypto" | "forex",
): MarketStructure {
  const swings = detectSwings(candles);
  const latestHigh = swings.filter(s => s.kind === "high").at(-1);
  const latestLow = swings.filter(s => s.kind === "low").at(-1);
  const candidates: GapZone[] = [];
  const minimum = atr * 0.15;

  for (let i = Math.max(2, candles.length - 100); i < candles.length; i++) {
    const before = candles[i - 2], previous = candles[i - 1], current = candles[i];
    const contiguous = Math.abs(current.time - previous.time - seconds) < 2 &&
      Math.abs(previous.time - before.time - seconds) < 2;
    const sessionGap = market === "forex" &&
      current.time - previous.time > seconds * 1.5 &&
      current.time - previous.time < 4 * 86400;

    const add = (kind: GapZone["kind"], direction: GapZone["direction"], lower: number, upper: number) => {
      if (upper - lower < minimum) return;
      // One price void can satisfy both patterns; counting it twice would fake an overlap.
      if (candidates.some(z => z.formedIndex === i && z.direction === direction &&
        Math.min(z.upper, upper) - Math.max(z.lower, lower) >= .8 * Math.min(z.upper - z.lower, upper - lower))) return;
      let penetration = 0;
      for (let j = i + 1; j < candles.length; j++) {
        const touched = direction === "bullish" ? upper - candles[j].low : candles[j].high - lower;
        penetration = Math.max(penetration, touched);
      }
      const liveTouch = direction === "bullish" ? upper - price : price - lower;
      penetration = Math.max(penetration, liveTouch);
      const fillPercent = Math.min(100, Math.max(0, 100 * penetration / (upper - lower)));
      if (fillPercent >= 100) return;
      candidates.push({
        kind, direction, lower, upper, formedAt: current.time, formedIndex: i,
        fillPercent, overlapCount: 1, distance: intervalDistance(price, lower, upper),
      });
    };

    if (contiguous) {
      if (current.low > before.high) add("fvg", "bullish", before.high, current.low);
      if (current.high < before.low) add("fvg", "bearish", current.high, before.low);
    }
    if (contiguous || sessionGap) {
      if (current.low > previous.high) add("candle", "bullish", previous.high, current.low);
      if (current.high < previous.low) add("candle", "bearish", current.high, previous.low);
    }
  }

  // Adjacent FVGs from the same displacement are one event, not independent confirmation.
  const eventIds = new Map<GapZone, string>();
  for (const direction of ["bullish", "bearish"] as const) {
    let group = 0, previousIndex = -Infinity;
    for (const zone of candidates.filter(z => z.direction === direction).sort((a, b) => a.formedIndex - b.formedIndex)) {
      if (zone.formedIndex - previousIndex > 2) group++;
      eventIds.set(zone, `${direction}-${group}`);
      previousIndex = zone.formedIndex;
    }
  }

  for (const zone of candidates) {
    const overlappingEvents = new Set<string>();
    for (const other of candidates) {
      if (zone === other || zone.direction !== other.direction || eventIds.get(zone) === eventIds.get(other)) continue;
      const lower = Math.max(zone.lower, other.lower);
      const upper = Math.min(zone.upper, other.upper);
      if (upper - lower < .25 * Math.min(zone.upper - zone.lower, other.upper - other.lower)) continue;
      overlappingEvents.add(eventIds.get(other)!);
      if (zone.overlapLower === undefined || upper - lower > zone.overlapUpper! - zone.overlapLower) {
        zone.overlapLower = lower;
        zone.overlapUpper = upper;
      }
    }
    zone.overlapCount += overlappingEvents.size;
    const matches = swings.filter(s => s.kind === (zone.direction === "bullish" ? "low" : "high"))
      .filter(s => candles.length - s.index <= 70)
      .sort((a, b) =>
        intervalDistance(a.price, zone.overlapLower ?? zone.lower, zone.overlapUpper ?? zone.upper) -
        intervalDistance(b.price, zone.overlapLower ?? zone.lower, zone.overlapUpper ?? zone.upper));
    const nearest = matches[0];
    if (nearest && intervalDistance(nearest.price, zone.overlapLower ?? zone.lower, zone.overlapUpper ?? zone.upper) <= atr * .35)
      zone.swing = nearest;
  }

  const ranked = candidates.sort((a, b) => {
    const score = (z: GapZone) => (z.swing ? 3 : 0) + (z.overlapCount > 1 ? 2 : 0) -
      z.distance / Math.max(atr, Number.EPSILON) - z.fillPercent / 100;
    return score(b) - score(a) || b.formedAt - a.formedAt;
  });
  const focus = ranked.find(z => z.distance <= 2 * atr);
  return { gaps: ranked.slice(0, 5), activeGapCount: ranked.length, swings: swings.slice(-12), latestHigh, latestLow, focus };
}
