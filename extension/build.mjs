import { build } from "esbuild";
import { copyFile, mkdir, rm, readFile, writeFile } from "node:fs/promises";

// Resolve paths relative to this script, even when invoked from another folder.
const root = new URL("./", import.meta.url);
const testing = process.argv.includes("--test");
const api = new URL(testing ? "http://127.0.0.1:18076" : (process.env.ANTISLOP_API_BASE_URL ?? "http://127.0.0.1:8000"));
if (api.username || api.password || api.search || api.hash || api.pathname !== "/" ||
    (api.protocol !== "https:" && !(api.protocol === "http:" && ["localhost", "127.0.0.1"].includes(api.hostname)))) {
  throw new Error("API base URL must be an HTTPS origin (HTTP allowed only for loopback development).");
}
const dist = new URL(testing ? "dist-test/" : "dist/", root);
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await build({
  entryPoints: ["content", "popup", "background"].map((name) => new URL(`src/${name}.ts`, root).pathname),
  outdir: dist.pathname,
  define: { __ANTISLOP_API_BASE_URL__: JSON.stringify(api.origin) },
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "chrome110",
  sourcemap: true,
  logLevel: "info",
});
for (const file of ["content.css", "popup.html", "popup.css"]) {
  await copyFile(new URL(file, root), new URL(file, dist));
}
const manifest = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));
manifest.host_permissions = [`${api.protocol}//${api.hostname}/*`];
await writeFile(new URL("manifest.json", dist), JSON.stringify(manifest, null, 2) + "\n");
console.log(`Built extension/${testing ? "dist-test" : "dist"} — ready to load unpacked.`);
