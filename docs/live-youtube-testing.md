# Live YouTube smoke test — 2026-11-01

Tested the locally loaded v0.1.0 extension in Chrome on real YouTube pages.
This is a limited smoke test, not full live compatibility certification.
No real-channel reports or appeals were submitted and no blocklist entries were changed.

| Surface | Observed result |
| --- | --- |
| Search | Report controls appeared on 11 of 12 initially observed cards. After scrolling, 20 controls on 21 cards; no duplicate direct report controls found. |
| Report dialog | Opened on a real card, displayed its handle, explained the three submitted fields, and requested a stable channel ID because only a handle was available. Cancel removed the dialog. |
| Home | 37 rich-item containers; 16 exposed channel links, all 16 received controls, with no duplicate controls per rich-item container. |
| Watch recommendations | Eight newer lockup cards, none with channel links, and no report controls. Two sampled cards contained only video links. Playback was paused after inspection. |

The current selectors cannot identify channels in the observed watch-page layout.
Skipping these cards avoids guessing from names or sending browsing activity to a
resolver. This is an actual coverage limitation: that layout cannot currently be
filtered by channel. Counts are snapshots of dynamic pages, not fixed expectations.

Live Blur/Collapse/Hide, reveal, appeal, popup preference changes, and end-to-end
sync were not verified in this smoke test. Their existing fixture tests do not
substitute for those live checks. A separate, clearly temporary local test setup
is needed to trigger filtering without falsely adding creators to the community
blocklist. Do not claim all live checks passed.
