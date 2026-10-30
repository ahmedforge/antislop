import { watchBlocklist } from "./blocklist-cache";
import { SELECTORS } from "./selectors";

import { applyFilter, setBlocklist, type Channel } from "./filter";
import { DEFAULT_SETTINGS, watchSettings } from "./settings";
let settings = { ...DEFAULT_SETTINGS };

function extractChannel(card: Element): Channel | null {
  const channel: Channel = { channelId: null, handle: null };
  for (const link of card.querySelectorAll<HTMLAnchorElement>(SELECTORS.channelLinks)) {
    let url: URL;
    try {
      url = new URL(link.href, location.origin);
    } catch {
      continue;
    }
    if (!['www.youtube.com', 'youtube.com'].includes(url.hostname)) continue;
    const id = url.pathname.match(/^\/channel\/(UC[\w-]{22})(?:\/|$)/);
    const handle = url.pathname.match(/^\/@([^/]+)(?:\/|$)/);
    if (id) channel.channelId ??= id[1];
    if (handle) {
      try {
        channel.handle ??= `@${decodeURIComponent(handle[1])}`;
      } catch {
        // Ignore malformed percent encoding in a link.
      }
    }
  }
  return channel.channelId || channel.handle ? channel : null;
}

const pending = new Set<Element>();
let scheduled = false;

function queueCard(candidate: Element): void {
  // A rich-item may contain a lockup: treat the outermost card as one card.
  let card = candidate;
  let parent = card.parentElement?.closest(SELECTORS.cards);
  while (parent) {
    card = parent;
    parent = card.parentElement?.closest(SELECTORS.cards);
  }
  pending.add(card);
}

function collect(root: Element): void {
  const containingCard = root.closest(SELECTORS.cards);
  if (containingCard) queueCard(containingCard);
  for (const card of root.querySelectorAll(SELECTORS.cards)) queueCard(card);
}

function flush(): void {
  scheduled = false;
  for (const card of pending) {
    if (!card.isConnected) continue;
    const channel = extractChannel(card);
    applyFilter(card, channel, settings);
  }
  pending.clear();
}

function scheduleFlush(): void {
  if (!scheduled && pending.size) {
    scheduled = true;
    requestAnimationFrame(flush);
  }
}

const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (mutation.target instanceof Element) {
      const card = mutation.target.closest(SELECTORS.cards);
      if (card) queueCard(card);
    }
    for (const node of mutation.addedNodes) {
      if (node instanceof Element) collect(node);
    }
  }
  scheduleFlush();
});

observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["href"],
});
watchBlocklist((channels) => {
  setBlocklist(channels);
  collect(document.documentElement);
  scheduleFlush();
});
watchSettings((next) => {
  settings = next;
  collect(document.documentElement);
  scheduleFlush();
});
collect(document.documentElement);
scheduleFlush();
