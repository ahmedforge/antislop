import { test, expect, chromium, type BrowserContext, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { createServer, type Server } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const API = "http://127.0.0.1:18076/v1/blocklist";
const T1 = "2026-10-31T00:00:00.123456Z", T2 = "2026-10-31T00:00:01.654321Z";
const ID = "UC0000000000000000000000", OTHER_ID = "UC1111111111111111111111";
const extensionPath = path.resolve("dist-test");
const extensionId = createHash("sha256").update(extensionPath).digest("hex").slice(0, 32)
  .replace(/[0-9a-f]/g, (c) => String.fromCharCode(97 + parseInt(c, 16)));
const original = { youtube_channel_id: ID, handle: "@antislop-demo-fixture", updated_at: T1 };
const fixture = `<!doctype html><style>ytd-video-renderer { display:block; width:320px; margin:12px; } .content {height:180px}</style>
<ytd-video-renderer id="flagged"><div class="content"><a href="/@antislop-demo-fixture">Demo</a></div></ytd-video-renderer>
<ytd-video-renderer id="renamed"><div class="content"><a href="/@new-handle">New handle</a></div></ytd-video-renderer>
<ytd-video-renderer id="stable"><div class="content"><a href="/channel/${ID}">Stable ID</a></div></ytd-video-renderer>
<ytd-video-renderer id="unlisted"><div class="content"><a href="/channel/${OTHER_ID}">Other ID</a><a href="/@antislop-demo-fixture">Reassigned handle</a></div></ytd-video-renderer>`;
let server: Server, context: BrowserContext, profile: string, popup: Page, page: Page;
let mode: "ok" | "offline" | "503" | "malformed" | "bad-cursor" | "unsolicited-304" | "422-delta";
let channels: typeof original[], removals: string[], cursor: string, warnings: number;
let requests: { url: URL; headers: Record<string, unknown>; status: number }[];

async function openBrowser() {
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium", headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
  });
  context.on("console", (message) => {
    if (message.text().includes("Blocklist sync unavailable")) warnings++;
  });
  await context.route("https://www.youtube.com/**", (route) => route.fulfill({ contentType: "text/html", body: fixture }));
  popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await expect(popup.locator("#mode")).toBeEnabled();
  page = await context.newPage();
  await page.goto("https://www.youtube.com/watch?v=private-test-video");
}
async function launch(offline = false) {
  if (offline) mode = "offline";
  profile = await mkdtemp(path.join(tmpdir(), "antislop-sync-"));
  await openBrowser();
  if (!offline) {
    await expect.poll(async () => (await cache())?.cursor).toBe(T1);
    await expect(page.locator("#flagged")).toHaveClass(/antislop-blur/);
  }
}
async function cache(): Promise<any> {
  return popup.evaluate(async () => (await chrome.storage.local.get("blocklistCache")).blocklistCache);
}
async function alarm() {
  await popup.evaluate(() => chrome.alarms.create("antislop-blocklist-sync", { when: Date.now() + 50 }));
}
async function sync() {
  const previous = (await cache())?.lastSyncedAt ?? 0;
  await alarm();
  await expect.poll(async () => (await cache())?.lastSyncedAt ?? 0).toBeGreaterThan(previous);
}

test.beforeAll(async () => {
  server = createServer((request, response) => {
    const url = new URL(request.url!, API);
    if (url.pathname !== "/v1/blocklist") { response.writeHead(404).end(); return; }
    const record = { url, headers: request.headers as Record<string, unknown>, status: 0 };
    requests.push(record);
    if (mode === "offline") { record.status = -1; request.socket.destroy(); return; }
    if (mode === "503") { record.status = 503; response.writeHead(503, { "Retry-After": "5" }).end(); return; }
    if (mode === "unsolicited-304") { record.status = 304; response.writeHead(304).end(); return; }
    if (mode === "422-delta" && url.searchParams.has("since")) { record.status = 422; response.writeHead(422).end(); return; }
    const body = mode === "malformed" ? '{"channels":false}' : JSON.stringify({
      full_sync: !url.searchParams.has("since"), channels,
      removed_channel_ids: url.searchParams.has("since") ? removals : [],
      next_since: mode === "bad-cursor" ? "1970-01-01T00:00:00Z" : cursor,
    });
    const etag = '"' + createHash("sha256").update(body).digest("hex") + '"';
    record.status = request.headers["if-none-match"] === etag ? 304 : 200;
    response.writeHead(record.status, { "Content-Type": "application/json", ETag: etag, "Cache-Control": "public, no-cache" });
    response.end(record.status === 304 ? undefined : body);
  });
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(18076, "127.0.0.1", resolve); });
});
test.afterAll(async () => { await new Promise<void>((resolve) => server.close(() => resolve())); });
test.beforeEach(() => {
  mode = "ok"; channels = [{ ...original }]; removals = []; cursor = T1; requests = []; warnings = 0;
});
test.afterEach(async () => {
  await context?.close();
  if (profile) await rm(profile, { recursive: true, force: true });
});

test("first sync is full; alarm, local cache and privacy boundaries are correct", async () => {
  await launch();
  expect(requests[0].url.search).toBe("");
  expect((await cache()).source).toBe(API);
  expect((await cache()).channels).toEqual([original]);
  expect((await popup.evaluate(() => chrome.alarms.get("antislop-blocklist-sync")))?.periodInMinutes).toBe(60);
  expect(await popup.evaluate(() => chrome.storage.sync.get(null))).toEqual({});
  await expect(page.locator("#unlisted")).not.toHaveClass(/antislop-/);
  for (const request of requests) {
    expect(request.url.pathname).toBe("/v1/blocklist");
    expect([...request.url.searchParams.keys()].every((key) => key === "since")).toBe(true);
    expect(request.headers.referer).toBeUndefined();
    expect(request.headers.cookie).toBeUndefined();
    expect(JSON.stringify(request.headers)).not.toContain("private-test-video");
  }
});

test("deltas preserve microseconds and invalidate old handles without changing mode", async () => {
  await launch();
  await popup.locator("#mode").selectOption("collapse");
  channels = [{ ...original, handle: "@new-handle", updated_at: T2 }]; cursor = T2;
  await sync();
  expect(requests.at(-1)!.url.searchParams.get("since")).toBe(T1);
  expect(requests.at(-1)!.headers["if-none-match"]).toBeUndefined();
  await expect(page.locator("#flagged")).not.toHaveClass(/antislop-/);
  await expect(page.locator("#renamed")).toHaveClass(/antislop-collapse/);
  await expect(page.locator("#stable")).toHaveClass(/antislop-collapse/);
  expect((await cache()).cursor).toBe(T2);
  await expect(popup.locator("#mode")).toHaveValue("collapse");
});

test("removals unhide cards live and are safe to replay", async () => {
  await launch();
  await popup.locator("#mode").selectOption("hide");
  await expect(page.locator("#flagged")).toBeHidden();
  channels = []; removals = [ID]; cursor = T2;
  await sync();
  await expect(page.locator("#flagged")).toBeVisible();
  expect((await cache()).channels).toEqual([]);
  await sync();
  expect((await cache()).channels).toEqual([]);
  await expect(popup.locator("#mode")).toHaveValue("hide");
});

test("ETags are scoped to the exact delta URL and 304 retains the cached list", async () => {
  await launch();
  await sync();
  const before = await cache();
  await sync();
  expect(requests.at(-1)!.status).toBe(304);
  expect(requests.at(-1)!.headers["if-none-match"]).toBe(before.validator.etag);
  expect((await cache()).channels).toEqual(before.channels);
  expect((await cache()).cursor).toBe(before.cursor);
});

for (const failure of ["offline", "503", "malformed", "bad-cursor", "unsolicited-304"] as const) {
  test(`${failure} preserves cache, cursor, and usable popup`, async () => {
    await launch();
    const before = await cache(), oldWarnings = warnings;
    mode = failure;
    await alarm();
    await expect.poll(() => warnings).toBeGreaterThan(oldWarnings);
    expect(await cache()).toEqual(before);
    await popup.locator("#mode").selectOption("collapse");
    await expect(page.locator("#flagged")).toHaveClass(/antislop-collapse/);
    await popup.locator("#enabled").uncheck();
    await expect(page.locator("#flagged")).not.toHaveClass(/antislop-/);
    mode = "ok";
    await sync();
  });
}

test("first install offline leaves cards visible until a successful retry", async () => {
  await launch(true);
  await expect.poll(() => warnings).toBeGreaterThan(0);
  expect(await cache()).toBeUndefined();
  await expect(page.locator("#flagged")).not.toHaveClass(/antislop-/);
  mode = "ok";
  await sync();
  await expect(page.locator("#flagged")).toHaveClass(/antislop-blur/);
});

test("422 recovers with a full snapshot and replaces obsolete entries", async () => {
  await launch();
  mode = "422-delta";
  channels = [{ youtube_channel_id: OTHER_ID, handle: "@new-handle", updated_at: T2 }]; cursor = T2;
  await sync();
  expect(requests.at(-2)!.status).toBe(422);
  expect(requests.at(-1)!.url.search).toBe("");
  expect(requests.at(-1)!.headers["if-none-match"]).toBeUndefined();
  expect((await cache()).channels.map((entry: any) => entry.youtube_channel_id)).toEqual([OTHER_ID]);
  await expect(page.locator("#flagged")).not.toHaveClass(/antislop-/);
  await expect(page.locator("#renamed")).toHaveClass(/antislop-blur/);
});

test("browser restart retains cache offline and recovers a deleted alarm", async () => {
  await launch();
  await popup.locator("#mode").selectOption("collapse");
  const before = await cache();
  await popup.evaluate(() => chrome.alarms.clear("antislop-blocklist-sync"));
  await context.close();
  mode = "offline";
  await openBrowser();
  await expect(page.locator("#flagged")).toHaveClass(/antislop-collapse/);
  expect(await cache()).toEqual(before);
  await expect.poll(async () => (await popup.evaluate(() => chrome.alarms.get("antislop-blocklist-sync")))?.periodInMinutes).toBe(60);
  await expect.poll(() => warnings).toBeGreaterThan(0);
  mode = "ok"; channels = []; removals = [ID]; cursor = T2;
  await sync();
  await expect(page.locator("#flagged")).not.toHaveClass(/antislop-/);
});
