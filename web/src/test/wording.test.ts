import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = join(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "test" ? [] : files(p);
    return /\.tsx?$/.test(f) && !f.endsWith(".gen.ts") ? [p] : [];
  });
}

describe("wording ban", () => {
  it('never claims "real-time", "realtime" or "live rates" (only the negated disclaimer is allowed)', () => {
    for (const f of files(SRC)) {
      const text = readFileSync(f, "utf8").replaceAll("not real-time", "");
      expect(text, f).not.toMatch(/real[- ]?time|live (?:rates|data)/i);
    }
  });

  it("only OfferAmount reads offer maximum amounts", () => {
    const readers = files(SRC).filter((f) => /\.amount_max\b/.test(readFileSync(f, "utf8")));
    expect(readers.map((f) => f.split("/").pop())).toEqual(["OfferAmount.tsx"]);
  });

  it("official links open in a new tab with noopener noreferrer", () => {
    const text = readFileSync(join(SRC, "components", "SourceLink.tsx"), "utf8");
    expect(text).toContain('target="_blank"');
    expect(text).toContain('rel="noopener noreferrer"');
  });
});

describe("no scores or weights in the front end (owner decision 2026-10-19)", () => {
  it("no component reads a result score, its components or scoring weights", () => {
    for (const f of files(SRC)) {
      const text = readFileSync(f, "utf8");
      expect(text, f).not.toMatch(/\.score\b|\.components\b|ScoreBreakdown|\bweights?\b\s*[:=]/);
      expect(text, f).not.toMatch(/score of 100|Score weights/i);
    }
  });
});
