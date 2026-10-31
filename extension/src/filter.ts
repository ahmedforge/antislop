import { openSubmission } from "./submission-ui";
import type { Entry } from "./blocklist-cache";
import type { Settings } from "./settings";

export type Channel = { channelId: string | null; handle: string | null };
let ids = new Set<string>();
let handles = new Set<string>();
let handleIds = new Map<string, Set<string>>();
export function setBlocklist(channels: Entry[]): void {
  ids = new Set(channels.map((entry) => entry.youtube_channel_id));
  handles = new Set(channels.flatMap((entry) => entry.handle ? [entry.handle.toLowerCase()] : []));
  handleIds = new Map();
  for (const entry of channels) {
    if (!entry.handle) continue;
    const key = entry.handle.toLowerCase();
    const matches = handleIds.get(key) ?? new Set<string>();
    matches.add(entry.youtube_channel_id);
    handleIds.set(key, matches);
  }
}
export function resolveChannelId(channel: Channel | null): string | null {
  if (channel?.channelId) return channel.channelId;
  const matches = channel?.handle ? handleIds.get(channel.handle.toLowerCase()) : undefined;
  return matches?.size === 1 ? [...matches][0] : null;
}
const classes = ["antislop-blur", "antislop-collapse", "antislop-hide"];
type CardState = {
  identity: string;
  revealed: boolean;
  panel: HTMLDivElement;
  label: HTMLSpanElement;
  button: HTMLButtonElement;
  appeal: HTMLButtonElement;
  channel: Channel | null;
  inertChildren: Map<HTMLElement, boolean>;
};
const states = new WeakMap<Element, CardState>();

function restoreChildren(state: CardState): void {
  for (const [child, wasInert] of state.inertChildren) child.inert = wasInert;
  state.inertChildren.clear();
}

export function applyFilter(card: Element, channel: Channel | null, settings: Settings): void {
  const identity = JSON.stringify(channel);
  let state = states.get(card);
  if (state && state.identity !== identity) {
    restoreChildren(state);
    state.identity = identity;
    state.revealed = false;
  }
  if (state) state.channel = channel;
  const flagged = channel && (
    channel.channelId !== null
      ? ids.has(channel.channelId)
      : channel.handle !== null && handles.has(channel.handle.toLowerCase())
  );
  if (!flagged || !settings.enabled || state?.revealed) {
    card.classList.remove(...classes);
    if (state) {
      state.panel.hidden = true;
      restoreChildren(state);
    }
    return;
  }
  if (!state) {
    const panel = document.createElement("div");
    panel.className = "antislop-panel";
    const label = document.createElement("span");
    const button = document.createElement("button");
    button.type = "button";
    const appeal = document.createElement("button");
    appeal.type = "button";
    appeal.textContent = "This is wrong";
    panel.append(label, button, appeal);
    state = { identity, revealed: false, panel, label, button, appeal, channel, inertChildren: new Map() };
    states.set(card, state);
    const savedState = state;
    appeal.addEventListener("click", (event) => {
      event.preventDefault(); event.stopPropagation();
      if (event.isTrusted && savedState.channel) openSubmission("appeal", { ...savedState.channel }, resolveChannelId(savedState.channel));
    });
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      savedState.revealed = true;
      card.classList.remove(...classes);
      panel.hidden = true;
      restoreChildren(savedState);
    });
  }
  // YouTube may replace a card's children while keeping its outer element.
  if (state.panel.parentElement !== card) card.append(state.panel);
  for (const [child, wasInert] of state.inertChildren) {
    if (child.parentElement !== card) {
      child.inert = wasInert;
      state.inertChildren.delete(child);
    }
  }
  for (const child of card.children) {
    if (!(child instanceof HTMLElement) || child === state.panel) continue;
    if (!state.inertChildren.has(child)) state.inertChildren.set(child, child.inert);
    child.inert = true; // Blurred links must not remain keyboard-interactive.
  }
  for (const mode of ["blur", "collapse", "hide"] as const) {
    card.classList.toggle(`antislop-${mode}`, settings.mode === mode);
  }
  state.panel.hidden = settings.mode === "hide";
  const label = settings.mode === "collapse" ? "Hidden: AI channel" : "Flagged as AI content by the community";
  const button = settings.mode === "collapse" ? "Show" : "Show anyway";
  // Avoid mutations when the observer revisits our own panel insertion.
  if (state.label.textContent !== label) state.label.textContent = label;
  if (state.button.textContent !== button) state.button.textContent = button;
}
