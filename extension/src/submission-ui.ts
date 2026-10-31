import type { Channel } from "./filter";
import type { SubmissionMessage, SubmissionReply } from "./submission-worker";

type ReportControl = { button: HTMLButtonElement; channel: Channel | null; channelId: string | null };
const controls = new WeakMap<Element, ReportControl>();
let openDialog: HTMLDialogElement | null = null;

export function channelIdFromInput(input: string): string | null {
  const value = input.trim();
  if (/^UC[\w-]{22}$/.test(value)) return value;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !["youtube.com", "www.youtube.com"].includes(url.hostname)) return null;
    return /^\/channel\/(UC[\w-]{22})\/?$/.exec(url.pathname)?.[1] ?? null;
  } catch { return null; }
}

export function openSubmission(kind: "report" | "appeal", channel: Channel, channelId: string | null): void {
  openDialog?.close();
  const dialog = document.createElement("dialog");
  dialog.className = "antislop-dialog";
  dialog.setAttribute("aria-label", kind === "report" ? "Report channel as AI" : "Appeal channel flag");
  const form = document.createElement("form");
  const title = document.createElement("h2");
  title.textContent = kind === "report" ? "Report channel as AI" : "Appeal channel flag";
  const target = document.createElement("p");
  target.textContent = `Channel: ${channel.handle ?? channelId ?? "unknown"}`;
  const note = document.createElement("p");
  note.textContent = "Only this channel, your reason, and an anonymous installation ID will be sent. Submission does not change the blocklist automatically.";
  const channelLabel = document.createElement("label");
  channelLabel.textContent = "YouTube channel ID or channel URL";
  const identifier = document.createElement("input");
  identifier.type = "text";
  identifier.required = true;
  identifier.maxLength = 200;
  identifier.value = channelId ?? "";
  identifier.placeholder = "UC… or https://www.youtube.com/channel/UC…";
  identifier.readOnly = channelId !== null;
  channelLabel.append(identifier);
  const hint = document.createElement("p");
  hint.textContent = channelId ? "The channel ID was found locally." : "This card only exposes a handle. Enter its stable channel ID or /channel/ URL; we do not resolve your browsing history online.";
  const reasonLabel = document.createElement("label");
  reasonLabel.textContent = "Reason";
  const reason = document.createElement("textarea");
  reason.required = true;
  reason.maxLength = 2000;
  reason.rows = 4;
  reasonLabel.append(reason);
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = kind === "report" ? "Submit report" : "Submit appeal";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => dialog.close());
  form.append(title, target, note, channelLabel, hint, reasonLabel, submit, cancel, status);
  dialog.append(form);
  const opener = document.activeElement;
  dialog.addEventListener("close", () => {
    dialog.remove(); // Only our dialog; never remove or wrap YouTube card nodes.
    if (openDialog === dialog) openDialog = null;
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
  }, { once: true });
  let busy = false;
  let trustedSubmit = false;
  submit.addEventListener("click", (event) => { trustedSubmit = event.isTrusted; });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!event.isTrusted || !trustedSubmit || busy || !form.reportValidity()) return;
    trustedSubmit = false;
    const id = channelId ?? channelIdFromInput(identifier.value);
    if (!id || !reason.value.trim()) {
      status.textContent = "Enter a valid channel ID and a non-empty reason.";
      return;
    }
    busy = true;
    submit.disabled = true;
    identifier.disabled = true;
    reason.disabled = true;
    status.textContent = "Submitting…";
    const message: SubmissionMessage = { type: "antislop-submit", kind, channelId: id, reason: reason.value.trim() };
    void chrome.runtime.sendMessage(message).then((reply: SubmissionReply | undefined) => {
      if (!reply || typeof reply.ok !== "boolean" || typeof reply.message !== "string") throw new Error("Missing response");
      status.textContent = reply.message;
      if (reply.ok) {
        cancel.textContent = "Close";
      } else {
        busy = false; submit.disabled = false; identifier.disabled = false; reason.disabled = false;
      }
    }).catch(() => {
      status.textContent = "Could not confirm submission. Your text has been kept; please retry.";
      busy = false; submit.disabled = false; identifier.disabled = false; reason.disabled = false;
    });
  });
  document.body.append(dialog);
  openDialog = dialog;
  dialog.showModal();
}

export function updateReportControl(card: Element, channel: Channel | null, channelId: string | null): void {
  let control = controls.get(card);
  if (!control && channel) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "antislop-report";
    button.textContent = "Report as AI";
    control = { button, channel, channelId };
    controls.set(card, control);
    const saved = control;
    button.addEventListener("click", (event) => {
      event.preventDefault(); event.stopPropagation();
      if (event.isTrusted && saved.channel) openSubmission("report", { ...saved.channel }, saved.channelId);
    });
  }
  if (!control) return;
  control.channel = channel;
  control.channelId = channelId;
  control.button.hidden = channel === null;
  if (control.button.parentElement !== card) card.append(control.button);
}
