import { build } from "esbuild";
import { copyFile, mkdir, rm } from "node:fs/promises";

// Resolve paths relative to this script, even when invoked from another folder.
const root = new URL("./", import.meta.url);
const dist = new URL("dist/", root);
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await build({
  entryPoints: [new URL("src/content.ts", root).pathname],
  outfile: new URL("content.js", dist).pathname,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "chrome110",
  sourcemap: true,
  logLevel: "info",
});
await copyFile(new URL("manifest.json", root), new URL("manifest.json", dist));
console.log("Built extension/dist — ready to load unpacked.");
