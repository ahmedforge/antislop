import { test, expect, chromium, type BrowserContext, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

let context: BrowserContext;
let profile: string;
let page: Page;
let popup: Page;
const extensionPath = path.resolve("dist");
const extensionId = createHash("sha256").update(extensionPath).digest("hex").slice(0, 32)
  .replace(/[0-9a-f]/g, (c) => String.fromCharCode(97 + parseInt(c, 16)));
const fixture = `<!doctype html><style>
body { margin: 20px; } ytd-rich-item-renderer, ytd-video-renderer,
ytd-compact-video-renderer, yt-lockup-view-model { display:block; width:320px; margin:12px; }
.content { height:180px; background: #acd; }
</style>
<ytd-rich-item-renderer id="home"><yt-lockup-view-model><div class="content"><a href="/@antislop-demo-fixture">Demo</a></div></yt-lockup-view-model></ytd-rich-item-renderer>
<ytd-video-renderer id="search"><div class="content"><a href="/channel/UC0000000000000000000000">Demo ID</a></div></ytd-video-renderer>
<ytd-compact-video-renderer id="sidebar"><div class="content"><a href="/@ANTISLOP-DEMO-FIXTURE">Demo uppercase</a></div></ytd-compact-video-renderer>
<yt-lockup-view-model id="safe"><div class="content"><a href="/@unlisted-fixture">Unlisted</a></div></yt-lockup-view-model>`;

test.beforeAll(async () => {
  profile = await mkdtemp(path.join(tmpdir(), "antislop-browser-"));
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium", headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
  });
  await context.route("https://www.youtube.com/**", (route) => route.fulfill({ contentType: "text/html", body: fixture }));
  popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
});
test.afterAll(async () => {
  await context?.close();
  if (profile) await rm(profile, { recursive: true, force: true });
});
test.beforeEach(async () => {
  await popup.evaluate(() => chrome.storage.sync.clear());
  await popup.reload();
  await expect(popup.locator("#mode")).toBeEnabled();
  page = await context.newPage();
  await page.goto("https://www.youtube.com/");
  await expect(page.locator("#home")).toHaveClass(/antislop-blur/);
});
test.afterEach(async () => { await page?.close(); });

test("default blur covers all three layouts without duplicate nested controls", async () => {
  for (const id of ["home", "search", "sidebar"]) {
    await expect(page.locator(`#${id}`)).toHaveClass(/antislop-blur/);
    await expect(page.locator(`#${id} .antislop-panel`)).toHaveCount(1);
    await expect(page.locator(`#${id} > :first-child`)).toHaveCSS("filter", "blur(12px)");
    expect(await page.locator(`#${id} > :first-child`).evaluate((node) => (node as HTMLElement).inert)).toBe(true);
  }
  await expect(page.locator("#safe")).not.toHaveClass(/antislop-/);
  await expect(popup.locator("#mode")).toHaveValue("blur");
  await expect(popup.locator("#enabled")).toBeChecked();
  await expect(popup.locator("#warning")).toBeHidden();
});

test("collapse, hide, disable, and restore apply live and preserve nodes", async () => {
  await page.evaluate(() => { (window as any).originalCard = document.getElementById("home"); });
  const height = await page.locator("#home").evaluate((node) => node.getBoundingClientRect().height);
  await popup.locator("#mode").selectOption("collapse");
  await expect(page.locator("#home")).toHaveClass(/antislop-collapse/);
  await expect(page.locator("#home .antislop-panel")).toContainText("Hidden: AI channel");
  expect(await page.locator("#home").evaluate((node) => node.getBoundingClientRect().height)).toBeLessThan(height);
  await popup.locator("#mode").selectOption("hide");
  await expect(page.locator("#home")).toHaveCSS("display", "none");
  await expect(popup.locator("#warning")).toBeVisible();
  await popup.locator("#enabled").uncheck();
  await expect(page.locator("#home")).toBeVisible();
  await expect(page.locator("#home > :first-child")).toHaveCSS("filter", "none");
  expect(await page.evaluate(() => (window as any).originalCard === document.getElementById("home"))).toBe(true);
  await popup.locator("#mode").selectOption("blur");
  await popup.locator("#enabled").check();
  await expect(page.locator("#home")).toHaveClass(/antislop-blur/);
});

test("show anyway and show reveal one card and survive unrelated mutations", async () => {
  await page.getByRole("button", { name: "Show anyway" }).first().click();
  await expect(page.locator("#home")).not.toHaveClass(/antislop-blur/);
  expect(await page.locator("#home > :first-child").evaluate((node) => (node as HTMLElement).inert)).toBe(false);
  await page.locator("#home a").evaluate((node) => { node.textContent = "Changed title"; });
  await expect(page.locator("#home .antislop-panel")).toBeHidden();
  await popup.locator("#mode").selectOption("collapse");
  await page.locator("#search").getByRole("button", { name: "Show", exact: true }).click();
  await expect(page.locator("#search")).not.toHaveClass(/antislop-collapse/);
  await expect(page.locator("#sidebar")).toHaveClass(/antislop-collapse/);
});

test("late links, reused cards, and replacement children are reprocessed", async () => {
  await page.evaluate(() => {
    const card = document.createElement("ytd-video-renderer"); card.id = "late";
    document.body.append(card);
  });
  await page.locator("#late").evaluate((node) => { node.innerHTML = '<div><a href="/@antislop-demo-fixture">Late</a></div>'; });
  await expect(page.locator("#late")).toHaveClass(/antislop-blur/);
  await page.locator("#late a").evaluate((node) => node.setAttribute("href", "/@unlisted-fixture"));
  await expect(page.locator("#late")).not.toHaveClass(/antislop-blur/);
  await page.locator("#home").evaluate((node) => { node.innerHTML = '<div><a href="/@antislop-demo-fixture">Replacement</a></div>'; });
  await expect(page.locator("#home .antislop-panel")).toHaveCount(1);
  await expect(page.locator("#home .antislop-panel")).toBeVisible();
  await page.locator("#home a").evaluate((node) => node.removeAttribute("href"));
  await expect(page.locator("#home")).not.toHaveClass(/antislop-blur/);
});

test("settings persist across popup and page reloads; invalid settings fall back to blur", async () => {
  await popup.locator("#mode").selectOption("collapse");
  await expect(popup.locator("#status")).toHaveText("Saved");
  await popup.reload();
  await expect(popup.locator("#mode")).toHaveValue("collapse");
  await page.reload();
  await expect(page.locator("#home")).toHaveClass(/antislop-collapse/);
  await popup.evaluate(() => chrome.storage.sync.set({ mode: "invalid", enabled: "invalid" }));
  await expect(page.locator("#home")).toHaveClass(/antislop-blur/);
  await expect(popup.locator("#mode")).toHaveValue("blur");
});
