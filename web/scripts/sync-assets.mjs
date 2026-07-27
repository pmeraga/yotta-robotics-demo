// Charts and video live at the repo root so the README can embed them directly.
// Astro only serves files under public/, so mirror them in before dev or build.
import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const pairs = [
  ["assets", "web/public/assets"],
  ["data", "web/public/data"],
];

for (const [from, to] of pairs) {
  const src = resolve(repoRoot, from);
  const dst = resolve(repoRoot, to);
  if (!existsSync(src)) {
    console.warn(`sync-assets: missing ${from}, skipping`);
    continue;
  }
  await rm(dst, { recursive: true, force: true });
  await mkdir(dirname(dst), { recursive: true });
  await cp(src, dst, { recursive: true });
  console.log(`sync-assets: ${from} -> ${to}`);
}
