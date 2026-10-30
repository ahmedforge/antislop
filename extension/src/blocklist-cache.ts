import { BLOCKLIST_URL, CACHE_KEY } from "./config";

export type Entry = { youtube_channel_id: string; handle: string | null; updated_at: string };
export type Cache = {
  version: 1;
  source: string;
  channels: Entry[];
  cursor: string;
  validator: { url: string; etag: string } | null;
  lastSyncedAt: number;
};
export type Delta = {
  full_sync: boolean;
  channels: Entry[];
  removed_channel_ids: string[];
  next_since: string;
};
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const validId = (value: unknown): value is string => typeof value === "string" && /^UC[\w-]{22}$/.test(value);

// Compare at PostgreSQL's microsecond precision without round-tripping through Date.
export function timestampKey(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid timestamp");
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/.exec(value);
  if (!match) throw new Error("Invalid timestamp");
  const time = Date.parse(`${match[1]}Z`);
  if (!Number.isFinite(time) || new Date(time).toISOString().slice(0, 19) !== match[1]) throw new Error("Invalid timestamp");
  return `${match[1]}.${(match[2] ?? "").padEnd(6, "0")}Z`;
}
function entries(value: unknown): Entry[] {
  if (!Array.isArray(value)) throw new Error("Invalid channels");
  const seen = new Set<string>();
  return value.map((entry: unknown) => {
    if (!object(entry) || !validId(entry.youtube_channel_id) || seen.has(entry.youtube_channel_id)) throw new Error("Invalid channel");
    if (entry.handle !== null && (typeof entry.handle !== "string" || !/^@\S+$/.test(entry.handle) || entry.handle.length > 100)) throw new Error("Invalid handle");
    timestampKey(entry.updated_at);
    seen.add(entry.youtube_channel_id);
    return { youtube_channel_id: entry.youtube_channel_id, handle: entry.handle, updated_at: entry.updated_at as string };
  });
}
export function parseDelta(value: unknown, since: string | null): Delta {
  if (!object(value) || value.full_sync !== (since === null)) throw new Error("Unexpected sync type");
  const next = timestampKey(value.next_since);
  if (since !== null && next < timestampKey(since)) throw new Error("Cursor moved backwards");
  const channels = entries(value.channels);
  if (!Array.isArray(value.removed_channel_ids) || !value.removed_channel_ids.every(validId)) throw new Error("Invalid removals");
  const removed = new Set(value.removed_channel_ids);
  if (removed.size !== value.removed_channel_ids.length || (since === null && removed.size > 0)) throw new Error("Invalid removals");
  for (const channel of channels) {
    const changed = timestampKey(channel.updated_at);
    if (changed > next || (since !== null && changed < timestampKey(since)) || removed.has(channel.youtube_channel_id)) throw new Error("Inconsistent delta");
  }
  return { full_sync: value.full_sync as boolean, channels, removed_channel_ids: [...removed], next_since: value.next_since as string };
}
export function parseCache(value: unknown): Cache | null {
  try {
    if (!object(value) || value.version !== 1 || value.source !== BLOCKLIST_URL || typeof value.lastSyncedAt !== "number" || !Number.isFinite(value.lastSyncedAt)) return null;
    const cursor = timestampKey(value.cursor);
    const channels = entries(value.channels);
    if (channels.some((channel) => timestampKey(channel.updated_at) > cursor)) return null;
    const validator = value.validator;
    if (validator !== null && (!object(validator) || typeof validator.url !== "string" || typeof validator.etag !== "string" || !/^"[a-f0-9]{64}"$/.test(validator.etag))) return null;
    return { version: 1, source: BLOCKLIST_URL, channels, cursor: value.cursor as string, validator: validator as Cache["validator"], lastSyncedAt: value.lastSyncedAt };
  } catch {
    return null;
  }
}
export function watchBlocklist(onUpdate: (channels: Entry[]) => void): void {
  let revision = 0;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !(CACHE_KEY in changes)) return;
    revision++;
    const value: unknown = changes[CACHE_KEY].newValue;
    const cache = parseCache(value);
    // A malformed replacement must not erase the last valid in-memory list.
    if (cache || value === undefined) onUpdate(cache?.channels ?? []);
  });
  const initialRevision = revision;
  void chrome.storage.local.get(CACHE_KEY).then((stored) => {
    if (revision !== initialRevision) return;
    const cache = parseCache(stored[CACHE_KEY]);
    if (cache) onUpdate(cache.channels);
  }).catch(() => { /* Keep the current list if storage is temporarily unavailable. */ });
}
