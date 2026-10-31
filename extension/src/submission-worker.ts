import { BLOCKLIST_URL } from "./config";

export type SubmissionMessage = {
  type: "antislop-submit";
  kind: "report" | "appeal";
  channelId: string;
  reason: string;
};
export type SubmissionReply = { ok: boolean; message: string };
let installPromise: Promise<string> | null = null;

function installId(): Promise<string> {
  if (installPromise) return installPromise;
  installPromise = (async () => {
    const stored = await chrome.storage.local.get("installId");
    if (typeof stored.installId === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(stored.installId)) return stored.installId;
    const id = crypto.randomUUID();
    // Persist before transmitting: retries and worker restarts reuse this ID.
    await chrome.storage.local.set({ installId: id });
    return id;
  })().finally(() => { installPromise = null; });
  return installPromise;
}

function validMessage(value: unknown): value is SubmissionMessage {
  if (value === null || typeof value !== "object") return false;
  const message = value as Partial<SubmissionMessage>;
  return message.type === "antislop-submit" && (message.kind === "report" || message.kind === "appeal") &&
    typeof message.channelId === "string" && /^UC[\w-]{22}$/.test(message.channelId) &&
    typeof message.reason === "string" && message.reason.trim().length > 0 && message.reason.trim().length <= 2000;
}
function trustedSender(sender: chrome.runtime.MessageSender): boolean {
  if (sender.id !== chrome.runtime.id || !sender.tab || !sender.url) return false;
  try {
    const url = new URL(sender.url);
    return url.protocol === "https:" && ["www.youtube.com", "youtube.com"].includes(url.hostname);
  } catch { return false; }
}
async function submit(message: SubmissionMessage): Promise<SubmissionReply> {
  try {
    const id = await installId();
    const url = new URL(message.kind === "report" ? "/v1/reports" : "/v1/appeals", BLOCKLIST_URL);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ install_id: id, channel_id: message.channelId, reason: message.reason.trim() }),
        credentials: "omit", referrerPolicy: "no-referrer", redirect: "error", cache: "no-store", signal: controller.signal,
      });
      if (response.status === 429) {
        const seconds = Number(response.headers.get("Retry-After"));
        const wait = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60;
        return { ok: false, message: `Too many submissions. Try again in ${wait} seconds. Your text has been kept.` };
      }
      if (response.status === 404 || response.status === 409) return { ok: false, message: "This channel is no longer available for an appeal. Your text has been kept." };
      if (response.status !== 200 && response.status !== 201) throw new Error("Submission unavailable");
      const data: unknown = await response.json();
      if (!data || typeof data !== "object" || typeof (data as { created?: unknown }).created !== "boolean") throw new Error("Invalid response");
      const created = (data as { created: boolean }).created;
      return { ok: true, message: created ? (message.kind === "report" ? "Report submitted for review." : "Appeal submitted for review.") : (message.kind === "report" ? "You have already reported this channel." : "You already have an open appeal for this channel.") };
    } finally { clearTimeout(timeout); }
  } catch {
    // No automatic retry: a failed request might have committed. Explicit retry
    // is safe because the backend deduplicates reports and open appeals.
    return { ok: false, message: "Could not confirm submission. Your text has been kept; please retry." };
  }
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  if (!validMessage(message) || !trustedSender(sender)) return false;
  void submit(message).then(sendResponse);
  return true; // Keep the response channel open while the fetch completes.
});
