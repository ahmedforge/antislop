# AntiSlop privacy

Applies to the repository's v0.1.0 extension and default backend configuration.
AntiSlop uses a community blocklist, not machine-learning detection. A deployed
operator must publish this policy with its own contact and retention arrangements.

## Data on your device

The content script reads channel IDs/handles from YouTube cards to compare them
with the downloaded blocklist. Card identity and per-card reveal choices remain
in page memory. AntiSlop does not store or transmit a watch history, video titles,
video URLs, searches, account identity, or a list of viewed channels.

`chrome.storage.local` holds approved channel IDs/handles, sync cursor, ETag,
API source URL, last successful sync time, and (after your first explicit
submission) a random installation UUID. `chrome.storage.sync` holds only the
chosen display mode and on/off preference; Chrome may sync these through your
browser account according to its settings. The installation UUID is not synced.
Form drafts remain in the open page and are discarded when closed or reloaded.

## Data sent to the configured API

- Blocklist requests send a sync timestamp and, when available, an ETag. They do
  not send your installation ID or any channel you are currently viewing.
- Explicit reports and appeals send exactly your installation UUID, the selected
  channel ID, and your typed reason. Avoid putting personal information in reasons.
  A failed confirmation can still mean the server saved the submission.
- Requests omit cookies and referrers and reject redirects. Network infrastructure
  necessarily sees the connecting IP address, request timing, and ordinary HTTP
  metadata. This is not a claim of network anonymity.

The UUID lets the backend associate submissions from the same installation and
prevent duplicates. It is pseudonymous, not proof of a person's identity.
The backend stores installation UUIDs/reputation, channel records, report/appeal
reasons and timestamps, appeal status, and moderation decisions with audit notes.
Authenticated administrators can review submissions; public endpoints do not
list reporters or their reasons. Approved channel IDs/handles and removal notices
are distributed publicly through the blocklist.

## Rate limits, metrics, and logs

For submissions, Redis stores token-bucket state under installation UUIDs and
SHA-256 hashes of socket peer IPs. The IP hash is unsalted and can be guessed; it
is not anonymization. Default expiry after the last accepted bucket consumption
is 300 seconds for installation buckets and 200 seconds for IP buckets. Rejected
requests do not refresh that expiry. Configured limits can change these periods.
Forwarded IP headers are not trusted by the supplied server configuration.

Prometheus records aggregate request counts, latency, created-report counts,
sync status counts, approved-channel count, database availability, and rejection
counts. Labels use HTTP method, route template, and status—not channel IDs,
installation IDs, reasons, IPs, or query strings. The metrics scrape itself is
excluded. Default retention is seven days with a 1 GB retained-block limit.
Grafana reads these aggregates. No advertising or third-party analytics SDK is
included. The supplied Grafana configuration disables analytics/update reporting.

Documented Uvicorn launch commands disable request access logs. Generic extension
sync warnings contain no browsing details. Operators must separately configure
reverse proxies, infrastructure logs, backups, and error reporting: this repository
cannot guarantee their retention or contents.

## Retention and control

Database submissions and moderation history currently have no automatic expiry
or self-service deletion endpoint. They persist until an operator removes them;
backups can retain copies. Uninstalling or clearing extension storage does not
delete previously submitted server records. A new installation ID does not remove
old submissions. No public service operator or deletion-contact address has been
established by this repository.

Disable filtering in the popup to stop applying display changes; this does not
stop background blocklist sync. Disable or uninstall the extension to stop its
background requests. Chrome manages removal of extension-local data and synced
preferences. Use the appeal form for a disputed channel flag; an appeal is a new
submission, not a request to erase personal data.
