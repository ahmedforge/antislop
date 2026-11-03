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

## Isolated end-to-end live test — 2026-11-03

A separately loaded extension named `AntiSlop — LOCAL TEST ONLY` targeted a
separate Compose project/API on port 18077, with its own PostgreSQL and Redis.
Its copied build used a 30-second alarm; the regular build retains hourly sync.
No changes to production extension source were needed for this test.

Verified through real YouTube search cards and the real local test backend:

1. The report form submitted a clearly labeled synthetic channel ID. The isolated
   admin queue received it as `pending_review` (test threshold was 1).
2. Only inside this isolated database, the synthetic ID was temporarily mapped
   to the visible card's handle to exercise filtering. This was test scaffolding,
   not a verified identity mapping or an allegation about the real creator.
3. Admin approval appeared in the downloaded blocklist; an alarm sync applied
   Blur automatically without reloading the page. The community label and
   `Show anyway`/`This is wrong` buttons rendered over the blurred live card.
4. `Show anyway` removed the blur while keeping the card in the page.
5. Reloading restored Blur. `This is wrong` opened an appeal, found the test
   channel ID locally, and submitted it successfully to the isolated backend.
6. Accepting that appeal removed the flag automatically on the live page.
   Final DOM inspection found zero cards with Blur/Collapse/Hide classes.

The synthetic record remains rejected in the isolated database as test history;
there is no active approved test flag. The regular blocklist was not modified
by this run. Screenshot: workspace `work/live-appeal-removal.jpg` (not committed).

This verifies report/moderation/sync/filter/reveal/appeal/removal across the real
browser and backend, with deliberately synthetic channel identity scaffolding.
Collapse, Hide, live popup settings changes, and a browser restart still need
live testing. The watch-page identity limitation described above is unresolved.
