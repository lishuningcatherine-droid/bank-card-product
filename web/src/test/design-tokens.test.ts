import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = join(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "test" ? [] : files(p);
    return /\.(tsx?|css)$/.test(f) && !f.endsWith(".gen.ts") ? [p] : [];
  });
}

const DEFAULT_PALETTE = /\b(?:bg|text|border|ring|outline|fill|stroke|from|to|via|decoration|accent|divide|placeholder)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black)(?:-\d{2,3})?\b/;

describe("design tokens (docs/DESIGN_SYSTEM.md)", () => {
  const all = files(SRC).filter((f) => !f.endsWith("globals.css"));
  it.each(all.map((f) => [relative(SRC, f), f]))("%s uses only theme tokens", (_name, f) => {
    const text = readFileSync(f, "utf8");
    expect(text).not.toMatch(/#[0-9a-fA-F]{3,8}\b(?![\w-]*[:=]\s*["'])/);
    expect(text).not.toMatch(/\b(?:rgb|rgba|hsl|hsla|oklch)\(/);
    expect(text).not.toMatch(/\b(?:bg|text|border|ring|fill|stroke)-\[(?:#|rgb|hsl)/);
    expect(text).not.toMatch(DEFAULT_PALETTE);
  });
});
