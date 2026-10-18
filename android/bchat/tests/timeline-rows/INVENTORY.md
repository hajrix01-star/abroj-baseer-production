# C11 pure timeline projection: pre-hook inventory

Reference: G2-C11 MessageTimeline phase 1 in `docs/build-governance/BCHAT-DEVELOPMENT-PROGRAM.md`.
Existing Activity source inspected at checkpoint `b8aa47a936a4ed99121990bc61708181714cea12`
(working CRLF SHA `6304A031502F47D26CDE4DE82DCEED8E045A9DB543D61313DA631A62211111E1`,
canonical Git LF SHA `3D13414D818811F2A2C5CEE34BE1606D02FDC3673F7302CC623D488F593EF562`).
This file is an inventory, not evidence of Activity integration or runtime improvement.

## Source fields and consumers

All Activity paths below are in `android/bchat/app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java`.
The new values are in the sibling `BChatTimelineRows.java`; no hooks were added to Activity.

| Existing source / consumer | Exact immutable presentation input |
| --- | --- |
| `validateMessageList`, `createMessageBubble`, `MessageTimelineAdapter` | Server `id`, `author_user_id`, `author_name`, `text`, `created_at` |
| `createMessageBubble`, `showMessageDetails` legacy read-only branch | Optional `delivery_state` and optional `read_at`; absent/null delivery stays absent, null and empty-string readAt remain distinct |
| `validateMessageList` / `ReplyWireContract`, quote preview | Reply absent, `{unavailable:true}`, or `id,author_name,text,optional media_kind` (nullable kind) |
| `MediaRecord`, `addConnectedMediaCard`, `addInlineAudioCard`, reply description | Exactly eight fields: `id,kind,mime,name,sha256,document_type,thumbnail_available,size` |
| `createLocalTextBubble`, `sync/BChatV2Outbox.Entry` | Durable SQLite `id`, `client_uuid`, `body`, five existing states queued/sending/uncertain/review/receipt |
| Pending action re-resolution | Local `replyToMessageId,reviewCode,messageId` hints; none is authenticated ACK proof |
| Date chip / same-sender / five-minute grouping | Previous server key/author/raw timestamp plus current author/raw timestamp. Local rows keep the current standalone behavior |
| Theme, language, layout, effective rights | Context locale/theme/bodySp/fontScale/density/width/RTL/offline, exact Rights revision+six flags, timezone/day key/12-24h |

The six display flags are chatView, chatSend, mediaView, mediaDownload,
deliverySupported, receiptsAvailable. They invalidate presentation; they are not authorization.
Wire MIME/size/UTF-8 validation and authentication remain at their existing source boundary.
The pure model performs identity, null/shape and bounded-character sanity checks, not a second wire policy.

`ReceiptDetailsProtocol.Page` reader identities/counts/deliveredAt/readAt remain in the separate
receipt-detail panel. Only the existing legacy message `read_at` is a timeline render/action input.
No account credentials, bitmap, media bytes, mutable JSON, View, Room or platform API enter these values.

## Identity and change contract

- Scope includes account key, user, room, current recipient membership, session and render owner.
- Existing stable IDs remain positive server ID / negative durable local SQLite ID / `Long.MIN_VALUE` EMPTY.
  Client UUID is separately compared exactly; no UUID/body hash is a stable ID or receipt.
- At most 500 sorted canonical server rows plus the existing 20 local rows. Input list order is retained.
  Empty is exactly one placeholder. No local row is filtered/deduplicated by matching body or media.
- `project` copies list structure; all retained values and exposed lists are immutable.
- `ChangePlan.between` is bounded linear work with exact map-key equality: remove old positions descending,
  insert new positions ascending, then change surviving rows at new positions. Scope change/reorder has an
  explicit full-reset fallback. No quadratic LCS or asynchronous publication lane is introduced.
- A changed predecessor ID/author/stamp invalidates the next server row even if that row's own body is unchanged.
- `AckTransition` is explicit caller-supplied UI correspondence after the existing authenticated ACK and
  durable retirement, never generated from body, media, local state or messageId hints. It must match the exact
  old local UUID/SQLite key and a present next canonical server row, with the pending row absent. It does not
  authenticate an ACK, mutate storage, retire an outbox row or relabel either stable identity.

## Future hook gate (not implemented here)

- Keep canonical `displayedMessages` as the source of truth. Publish canonical/projection/adapter notifications
  atomically on MAIN only after rechecking the current owner. Sync scrub/detach on logout, rights loss or rejoin.
- Preserve contiguous server prefix, inner Holder.bubble, actual binding position and receipt viewport/strict-cache
  gates; do not generate delivery/read ACK from rendering, diff, cache existence or FCM.
- Re-resolve reply/copy/details/media/pending actions against current scoped canonical data and current permissions.
- Preserve server-ID/pixel anchor, historical 500-row window, focus/follow-bottom policy and composer CAS/durable enqueue.
- Do not reuse media/audio/thumbnail/avatar subtrees before reviewing target leases, recycled holder cleanup,
  current membership and late callback rejection. Player ownership stays account/room/member/media, not holder.
- Date formatting/grouping stays in the existing visible binder; this phase does not parse/format 500 dates per poll.
- No claim of performance, allocation count, Android rendering, SQLite, auth, player, receipts or Activity acceptance
  follows from the pure JVM tests. C26 baseline and after artifacts were not modified or rerun.
