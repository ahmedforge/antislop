import "./submission-worker";
import { parseCache, parseDelta, type Cache, type Entry } from "./blocklist-cache";
import { BLOCKLIST_URL, CACHE_KEY, SYNC_ALARM, SYNC_PERIOD_MINUTES } from "./config";

let activeSync: Promise<void> | null = null;

async function fetchBlocklist(cache: Cache | null, full = false): Promise<void> {
  const since = full ? null : cache?.cursor ?? null;
  const url = new URL(BLOCKLIST_URL);
  if (since !== null) url.searchParams.set("since", since);
  // Cursor recovery must fetch a body even if an old full-snapshot ETag exists.
  const validator = !full && cache?.validator?.url === url.href ? cache.validator : null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, {
      headers: validator ? { "If-None-Match": validator.etag } : {},
      credentials: "omit",
      referrerPolicy: "no-referrer",
      redirect: "error",
      cache: "no-store",
      signal: controller.signal,
    });
    if (response.status === 304) {
      if (!cache || !validator) throw new Error("Unsolicited 304");
      await chrome.storage.local.set({ [CACHE_KEY]: { ...cache, lastSyncedAt: Date.now() } });
      return;
    }
    if (response.status === 422 && since !== null) {
      // A restored database or invalid old cursor needs a new snapshot. Retain
      // the old list until that snapshot has been successfully persisted.
      await fetchBlocklist(cache, true);
      return;
    }
    if (response.status !== 200) throw new Error("Sync unavailable");
    const body = await response.text();
    if (body.length > 5 * 1024 * 1024) throw new Error("Blocklist exceeds v1 size limit");
    const delta = parseDelta(JSON.parse(body), since);
    const merged = new Map<string, Entry>(
      delta.full_sync ? [] : (cache?.channels ?? []).map((entry) => [entry.youtube_channel_id, entry]),
    );
    for (const entry of delta.channels) merged.set(entry.youtube_channel_id, entry);
    for (const id of delta.removed_channel_ids) merged.delete(id);
    const etag = response.headers.get("ETag");
    const next: Cache = {
      version: 1,
      source: BLOCKLIST_URL,
      channels: [...merged.values()],
      cursor: delta.next_since, // Preserve the server's exact microsecond string.
      validator: etag && /^"[a-f0-9]{64}"$/.test(etag) ? { url: url.href, etag } : null,
      lastSyncedAt: Date.now(),
    };
    // One key prevents a cursor from being advanced separately from its data.
    await chrome.storage.local.set({ [CACHE_KEY]: next });
  } finally {
    clearTimeout(timeout);
  }
}

function synchronize(): Promise<void> {
  if (activeSync) return activeSync;
  activeSync = (async () => {
    const stored = await chrome.storage.local.get(CACHE_KEY);
    await fetchBlocklist(parseCache(stored[CACHE_KEY]));
  })().catch(() => {
    // No URLs, identities, response bodies, or browsing activity in diagnostics.
    console.warn("[AntiSlop] Blocklist sync unavailable; keeping the cached list.");
  }).finally(() => { activeSync = null; });
  return activeSync;
}

async function ensureAlarm(): Promise<boolean> {
  const alarm = await chrome.alarms.get(SYNC_ALARM);
  if (alarm?.periodInMinutes === SYNC_PERIOD_MINUTES) return false;
  await chrome.alarms.create(SYNC_ALARM, {
    delayInMinutes: SYNC_PERIOD_MINUTES,
    periodInMinutes: SYNC_PERIOD_MINUTES,
  });
  return true;
}
async function startSync(): Promise<void> {
  try {
    await ensureAlarm();
    await synchronize();
  } catch {
    console.warn("[AntiSlop] Sync scheduling unavailable; keeping the cached list.");
  }
}

// Register events synchronously so Chrome can dispatch them on worker wakeup.
chrome.runtime.onInstalled.addListener(() => { void startSync(); });
chrome.runtime.onStartup.addListener(() => { void startSync(); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SYNC_ALARM) void startSync();
});
// Alarms may disappear across browser restarts. Check on every worker startup,
// without moving an existing alarm's deadline or refetching on every wakeup.
void ensureAlarm().then((created) => { if (created) return synchronize(); }).catch(() => {
  console.warn("[AntiSlop] Sync scheduling unavailable; keeping the cached list.");
});
