import { build } from "esbuild";
import { copyFile, mkdir, rm } from "node:fs/promises";

// Resolve paths relative to this script, even when invoked from another folder.
const root = new URL("./", import.meta.url);
const dist = new URL("dist/", root);
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await build({
  entryPoints: ["content", "popup"].map((name) => new URL(`src/${name}.ts`, root).pathname),
  outdir: dist.pathname,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "chrome110",
  sourcemap: true,
  logLevel: "info",
});
for (const file of ["manifest.json", "content.css", "popup.html", "popup.css"]) {
  await copyFile(new URL(file, root), new URL(file, dist));
}
console.log("Built extension/dist — ready to load unpacked.");
