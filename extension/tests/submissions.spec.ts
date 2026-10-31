import { test, expect, chromium, type BrowserContext, type Page } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { createServer, type Server } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";

const FLAGGED = "UC0000000000000000000000", UNLISTED = "UC1111111111111111111111";
const root = path.resolve("dist-test");
const extensionId = createHash("sha256").update(root).digest("hex").slice(0,32).replace(/[0-9a-f]/g,c=>String.fromCharCode(97+parseInt(c,16)));
const html = `<ytd-video-renderer id="new"><div><a href="/channel/${UNLISTED}">New channel</a></div></ytd-video-renderer>
<ytd-video-renderer id="handle"><div><a href="/@unknown-fixture">Unknown handle</a></div></ytd-video-renderer>
<ytd-video-renderer id="flagged"><div><a href="/@antislop-demo-fixture">Flagged handle</a></div></ytd-video-renderer>
<style>ytd-video-renderer{display:block;width:400px;margin:12px}ytd-video-renderer>div{min-height:180px}</style>`;
let server: Server, context: BrowserContext, popup: Page, page: Page, profile: string;
let posts: { path: string; body: any; headers: any }[], stored: Map<string,string>;
let fail: "none" | "503" | "disconnect-after-commit";
async function openBrowser() {
  context = await chromium.launchPersistentContext(profile, { channel:"chromium",headless:true,args:[`--disable-extensions-except=${root}`,`--load-extension=${root}`] });
  await context.route("https://www.youtube.com/**", route=>route.fulfill({contentType:"text/html",body:html}));
  popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await expect(popup.locator("#mode")).toBeEnabled();
  page = await context.newPage();
  await page.goto("https://www.youtube.com/watch?v=private-video");
  await expect(page.locator("#flagged")).toHaveClass(/antislop-blur/);
}
async function openReport(target = "#new") {
  await page.locator(target).getByRole("button", {name:"Report as AI",exact:true}).click();
  return page.getByRole("dialog", {name:"Report channel as AI"});
}
test.beforeAll(async()=>{
  server=createServer((req,res)=>{
    if(req.method === "GET") {
      res.writeHead(200,{"Content-Type":"application/json"}).end(JSON.stringify({
        full_sync:!new URL(req.url!,"http://127.0.0.1").searchParams.has("since"),
        channels:[{youtube_channel_id:FLAGGED,handle:"@antislop-demo-fixture",updated_at:"2026-10-31T00:00:00.123456Z"}],
        removed_channel_ids:[],next_since:"2026-10-31T00:00:00.123456Z",
      })); return;
    }
    let raw=""; req.on("data",data=>raw+=data); req.on("end",()=>{
      const body=JSON.parse(raw); posts.push({path:req.url!,body,headers:req.headers});
      if(fail === "503") {res.writeHead(503).end();return;}
      const key=`${req.url}:${body.install_id}:${body.channel_id}`;
      const created=!stored.has(key); if(created)stored.set(key,randomUUID());
      if(fail === "disconnect-after-commit") {req.socket.destroy();return;}
      res.writeHead(created?201:200,{"Content-Type":"application/json"}).end(JSON.stringify({id:stored.get(key),created}));
    });
  });
  await new Promise<void>((resolve,reject)=>{server.once("error",reject);server.listen(18076,"127.0.0.1",resolve);});
});
test.afterAll(async()=>{await new Promise<void>(resolve=>server.close(()=>resolve()));});
test.beforeEach(async()=>{
  posts=[];stored=new Map();fail="none";
  profile=await mkdtemp("/tmp/antislop-submissions-"); await openBrowser();
});
test.afterEach(async()=>{await context?.close();if(profile)await rm(profile,{recursive:true,force:true});});

test("browsing, synthetic clicks, opening and cancelling send no submissions or install ID",async()=>{
  expect(await popup.evaluate(async()=>(await chrome.storage.local.get("installId")).installId)).toBeUndefined();
  await page.locator("#new .antislop-report").evaluate((node)=>(node as HTMLButtonElement).click());
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const dialog=await openReport();
  await dialog.getByLabel("Reason",{exact:true}).fill("A draft only");
  await dialog.locator("form").evaluate((node)=>(node as HTMLFormElement).requestSubmit());
  await dialog.getByRole("button",{name:"Cancel",exact:true}).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(posts).toEqual([]);
  expect(await popup.evaluate(async()=>(await chrome.storage.local.get("installId")).installId)).toBeUndefined();
});

test("explicit report sends only three fields and retries reuse one install ID",async()=>{
  let dialog=await openReport();
  await expect(dialog.getByLabel("YouTube channel ID or channel URL")).toHaveValue(UNLISTED);
  await dialog.getByLabel("Reason",{exact:true}).fill("  Generated narration  ");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Report submitted for review.");
  expect(posts).toHaveLength(1);
  expect(Object.keys(posts[0].body).sort()).toEqual(["channel_id","install_id","reason"]);
  expect(posts[0].body.channel_id).toBe(UNLISTED);
  expect(posts[0].body.reason).toBe("Generated narration");
  expect(posts[0].body.install_id).toMatch(/^[a-f0-9-]{14}4[a-f0-9-]+$/);
  expect(posts[0].headers.referer).toBeUndefined();expect(posts[0].headers.cookie).toBeUndefined();
  expect(JSON.stringify(posts)).not.toContain("private-video");
  expect(await popup.evaluate(async()=>(await chrome.storage.sync.get(null)).installId)).toBeUndefined();
  await expect(page.locator("#new")).not.toHaveClass(/antislop-blur/);
  await dialog.getByRole("button",{name:"Close",exact:true}).click();
  dialog=await openReport();
  await dialog.getByLabel("Reason",{exact:true}).fill("Retry");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("You have already reported this channel.");
  expect(posts[1].body.install_id).toBe(posts[0].body.install_id);
  expect(stored.size).toBe(1);
});

for(const mode of ["blur","collapse"])test(`This is wrong creates an appeal in ${mode} without revealing the card`,async()=>{
  await popup.locator("#mode").selectOption(mode);
  await page.locator("#flagged").getByRole("button",{name:"This is wrong",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"Appeal channel flag"});
  await expect(dialog.getByLabel("YouTube channel ID or channel URL")).toHaveValue(FLAGGED);
  await dialog.getByLabel("Reason",{exact:true}).fill("This channel contains original recordings");
  await dialog.getByRole("button",{name:"Submit appeal",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Appeal submitted for review.");
  expect(posts[0].path).toBe("/v1/appeals");expect(posts[0].body.channel_id).toBe(FLAGGED);
  await expect(page.locator("#flagged")).toHaveClass(new RegExp(`antislop-${mode}`));
});

test("handle-only reports require a stable ID and accept a channel URL",async()=>{
  const dialog=await openReport("#handle");
  const input=dialog.getByLabel("YouTube channel ID or channel URL");
  await expect(input).toHaveValue("");
  await input.fill("@unknown-fixture");
  await dialog.getByLabel("Reason",{exact:true}).fill("Explicit report");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Enter a valid channel ID and a non-empty reason.");
  expect(posts).toHaveLength(0);
  await input.fill(`https://www.youtube.com/channel/${UNLISTED}?feature=shared`);
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Report submitted for review.");
  expect(posts[0].body.channel_id).toBe(UNLISTED);
});

for(const failure of ["503","disconnect-after-commit"] as const)test(`${failure} keeps the draft and explicit retry is safe`,async()=>{
  fail=failure;
  const dialog=await openReport();
  await dialog.getByLabel("Reason",{exact:true}).fill("Keep this draft");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toContainText("Could not confirm submission");
  await expect(dialog.getByLabel("Reason",{exact:true})).toHaveValue("Keep this draft");
  await expect(dialog.getByRole("button",{name:"Submit report",exact:true})).toBeEnabled();
  const firstId=posts[0].body.install_id;
  fail="none";
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText(failure==="503"?"Report submitted for review.":"You have already reported this channel.");
  expect(posts.at(-1)!.body.install_id).toBe(firstId);
  expect(stored.size).toBe(1);
});

test("reused cards update the report target and installation ID survives browser restart",async()=>{
  await page.locator("#new a").evaluate((node)=>node.setAttribute("href","/channel/UC2222222222222222222222"));
  let dialog=await openReport();
  await expect(dialog.getByLabel("YouTube channel ID or channel URL")).toHaveValue("UC2222222222222222222222");
  await dialog.getByLabel("Reason",{exact:true}).fill("Updated card");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Report submitted for review.");
  const id=posts[0].body.install_id;
  await context.close();await openBrowser();
  dialog=await openReport();await dialog.getByLabel("Reason",{exact:true}).fill("Another channel");
  await dialog.getByRole("button",{name:"Submit report",exact:true}).click();
  await expect(dialog.getByRole("status")).toHaveText("Report submitted for review.");
  expect(posts.at(-1)!.body.install_id).toBe(id);
});
