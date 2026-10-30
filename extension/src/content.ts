import { SELECTORS } from "./selectors";

type Channel = { channelId: string | null; handle: string | null };

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

// Weak keys allow removed cards to be garbage collected. Store the identity,
// rather than a permanent "processed" marker: YouTube can reuse DOM elements.
const seen = new WeakMap<Element, string>();
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
    if (!channel) {
      seen.delete(card); // Retry when a late channel link arrives.
      continue;
    }
    const identity = JSON.stringify(channel);
    if (seen.get(card) === identity) continue;
    seen.set(card, identity);
    console.log("[AntiSlop] channel", channel);
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
collect(document.documentElement);
scheduleFlush();
console.log("[AntiSlop] observing YouTube cards (local diagnostics only)");
