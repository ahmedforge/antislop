// All YouTube DOM selectors belong here. YouTube can change these without notice.
export const SELECTORS = {
  cards: [
    "ytd-rich-item-renderer", // Home feed; wraps classic and newer card layouts.
    "ytd-video-renderer", // Search results.
    "ytd-compact-video-renderer", // Classic watch-page sidebar.
    "yt-lockup-view-model", // Newer search/sidebar layouts.
  ].join(","),
  channelLinks: 'a[href*="/channel/"], a[href*="/@"]',
} as const;
