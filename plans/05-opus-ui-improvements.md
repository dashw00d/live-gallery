# 05 — Fieldnotes UI improvements: a calm, usable T3 + Live Gallery harness

Status: design plan, 2026-11-15. Written by the Opus UI design planning lane. **No application code was changed or run for this plan.** I read the code, the approved mockup and the earlier plans, and I looked at the controller's existing screenshots. I did not start the app, open a browser, run tests or call a provider.

Read with: [01 product/roadmap](01-product-and-roadmap.md), [03 feed and UX](03-feed-and-ux.md), approved visual [`mockups/fieldnotes-monokai-vibrant.html`](../mockups/fieldnotes-monokai-vibrant.html), the board at `/home/ryan/dev/live-gallery-agents/BLACKBOARD.md`, and `AGENTS.md`. The `AGENTS.md` rules take priority over the earlier plans: this is a personal app that runs locally. Keep security proportionate, don't add permission friction, and keep tests proportionate.

Source inspected: the integration worktree `/home/ryan/.t3/worktrees/live-gallery/t3-2c3d524f-0aad681690c6ab7b` at `0b118cf`, **including uncommitted footer changes** to `assets/fieldnotes.{html,css,js}`. Line numbers below refer to that working tree.

Labels used throughout:
- **[verified-source]**: I read it in the code.
- **[verified-runtime]**: the controller recorded it on the board from real runs.
- **[proposal]**: a design in this plan. It is not built.

---

## 1. Where the build actually is

### 1.1 What works today

| Area | Today's behaviour | Evidence |
|---|---|---|
| Thread list | The client polls `/v1/threads` every 15 s. Each thread has `title`, `status`, `providerInstanceId` and `model`, and is shown in a `<select>`. | [verified-source] `fieldnotes.js:208-225` |
| Thread detail | `/v1/thread` returns up to 40 messages with no stable IDs. It also returns **`activeRunId`, `pendingRequestCount`, `branch`, `worktreePath` and `link`**, which the UI receives but **never displays**. | [verified-source] `src/t3_adapter.rs:112-131`, `fieldnotes.js:239` |
| Live stream | `/v1/live/selected` is an SSE stream of full projections. Messages carry `{id, threadId, runId, role, text, streaming, createdAt}`. Progress carries `{id, threadId, kind, status, label, outputOmitted}`. Backend delivery was proven with real Codex: the assistant message and command running→completed both arrived. Incremental token streaming was **not** proven, because the message arrived already finalised. | [verified-source] `src/server/live.rs:10-19,178` and `t3_projection.rs:70-80`. [verified-runtime] Waves 15–16 |
| Live rendering | Every frame calls `replaceChildren` on all messages, then **appends all progress rows after all messages**. Nothing is keyed and nothing preserves scroll. | [verified-source] `fieldnotes.js:171-177` |
| Gap and reconnect | When the stream gaps, the UI clears the content, falls back to polling and retries after 1 s, 3 s and 10 s. | [verified-source] `fieldnotes.js:180-193` |
| Send / create | Only works when the server starts with `--t3-allow-write`. Sends are once-only with an attempt ID; the draft is preserved on failure. If the outcome is unknown, the draft is blocked for the rest of the tab session. | [verified-source] `fieldnotes.js:262-306` |
| Feedback references | Inspector → "Add reference to draft" adds a path chip. **But a draft with any reference cannot be sent**: the UI disables Send and the server rejects any non-empty `references`. The feedback loop dead-ends. | [verified-source] `fieldnotes.js:265,271`, `src/server.rs:354` |
| Drafts | Kept per thread in tab memory and lost on reload. `draft_store.rs` exists but is not wired into the server. | [verified-source] `fieldnotes.js:122-146`, `src/main.rs:6` |
| Artifacts | Global manual watch roots. Newest-first listing (`app.rs:232`). Search, kind and root filters, freeze, load older, an image preview dialog and feedback. Kinds are **Image and Model only** (`item.rs:32-34`). The `/f/` routes don't support HTTP Range requests. | [verified-source] |
| Activity / Changes | Static "unavailable" paragraphs. | [verified-source] `fieldnotes.html` |
| Stop / approvals / children | Stop is a disabled dashed "Stop unavailable" button. There is no approval UI. Child threads are not discovered: the CLI path uses `includeSubagents:false`, and the MCP list exists but isn't wired. | [verified-source], plus the board's "workspace-discovery integration research" entry |
| Visual | Dark vibrant tokens, close to the mockup's override block (see §2.2). | [verified-source] `fieldnotes.css:1` |

### 1.2 The uncommitted footer (latest user request): review

The working tree moves the composer out of the Conversation view into a fixed `<footer class="conversation-dock">`. That footer adds an "Agent · latest message" line above the composer, so both stay visible on every tab. This matches the request, and the plan keeps it. From reading the code (not rendered), it has these defects:

1. **Status text appears as the agent's message.** `clearHistory(text)` writes connection and status strings into `#latest-agent-text` (`fieldnotes.js:202`). Examples: "Connecting to partial live snapshot…", "Live gap: content cleared…", "T3 read unavailable…". The footer then shows system text under the "Agent" label. Every live reconnect also blanks the last real agent message.
2. **Live tool progress never reaches the footer.** `renderLatestAgent` only looks at messages. A long command shows nothing "active".
3. **The left offset is hard-coded.** `left:220px` duplicates the sidebar width in `.shell{grid-template-columns:220px …}`. The ResizeObserver/padding workaround (`--dock-height`) exists only because the footer is `position:fixed`.
4. **Attach still jumps away.** Inspector "Add reference" forces `#conversation` (`fieldnotes.js:480`). Now that the draft is always visible, the user should stay where they were.
5. **The footer carries too much notice text.** `send-status` and `send-recovery` both render inside the dock, alongside the (now separated) `control-note` above the tabs. On small screens the dock can grow to 48vh.
6. **No destination is shown.** The dock never says *where* the text goes: which thread, or a new thread when on Scratch.

The milestone M0 below fixes all six without changing what the user asked for.

### 1.3 What the controller's screenshots show

Source: `current-conversation.png` and `current-artifacts.png`. These are pre-footer screenshots by the controller, not by me.

At 1440 px, the user sees **five separate disclaimer blocks** before the first message:
- the header destination paragraph
- the read-only note
- the polling notice
- the sidebar workspace note
- the artifacts rail paragraphs

Lowercase "user"/"assistant" boxes look like a debug log. "Stop unavailable" takes prime header space. The content is honest but tiring. The biggest everyday improvement is to **move honesty into compact state chips with details on demand**, not to add features.

---

## 2. Approved mockup vs. build: what to adopt, defer or drop

### 2.1 Element-by-element

| Mockup element | Build | Decision |
|---|---|---|
| Sidebar thread list as nav buttons with status dots and counts; "＋ New thread" | `<select>` | **Adopt in M1.** All the data exists (`status`, `title`). |
| Header: title, sub-line "project / branch · Thread", run chip, Stop ▾ | Long destination paragraph plus a disabled Stop | **Adopt in M1.** Use `branch`, provider and model, the status chip and `pendingRequestCount`. Replace Stop with "Open in T3 ↗" until stop is proven (§4.4). |
| Message: avatar initial, name, time, plain paragraphs | Bordered `user`/`assistant` boxes | **Adopt in M1** |
| Tool card inline in the turn ("● Rendering… live", command line, last output line) | Progress appended after everything; output is never shown | **Adopt in M1, partially.** Group rows inline by `runId` and show the label and status. No output line until the source provides it and the backend lane allows it. |
| "Needs attention · Question" card with "Draft a response" | None. `pendingRequestCount` is available but unused. | **M1 minimal version:** "N requests waiting · Answer in T3 ↗". A full answer card waits on a T3 control contract. |
| "NEW · 2 images observed in /work/renders · Open gallery" inline notice | None | **Adopt in M2** (§4.6) |
| Right rail on Conversation: Live outputs and Agents | None | **Live outputs in M2** (≥1200 px only). **Agents in M3**, once children are discovered. |
| Composer with "To: main agent · Terra xhigh · Queue next turn" and Send | The footer dock has no destination | **Adopt in M0** as the destination line in the dock |
| Stop menu: current run, force, background | Disabled | **Defer.** Do not render menu items for capabilities that are unproven. |
| Activity timeline | Placeholder | **M2: a timeline for this tab session only** (§4.7) |
| Changes: git status and diff, latest test | Placeholder | **M2: git status and diff for the thread's checkout** (§4.8). The test result is deferred. |
| Inspect as a full page with Back, a Details rail and revisions | Modal dialog | **Keep the dialog in M1–M2** and add prev/next. Make it a page in M4. |
| Gallery chips: All, Images, 3D, Video & audio, Code | Images + 3D | **Defer to M4**, because the backend kinds and Range support are missing |
| Timeline scrubber "Now ━━● 15 min ago" | None | **Drop for now.** There is no event history to scrub. |
| Top bar "● Transport connected", ⌘K | Connection text in the sidebar | **Adopt the connection chip in M1.** Drop ⌘K. |
| Agents page with parent/children cards | None | **M3**, depending on child discovery |
| Workspace settings: watched folders, "Add folder", capture & retention toggles | "Manage folders in legacy gallery ↗" | **Inline "Add folder" in M2** using the existing `/api/dirs` and `/api/watch`. Retention toggles wait for M4. |

### 2.2 Visual tokens

The approved mockup's final override block uses these tokens:
- `--bg:#16171d`, `--side:#15161b`, `--panel:#1b1c21`
- `--line:#596475` (the borders actually used are `#454751`/`#4e5666`)
- `--green:#81f900`, `--orange:#ff9700`, `--yellow:#ffd945`, `--pink:#ff4dff`, `--cyan:#19d1e5`
- primary button `#2b2636` / `#5b476d` / `#f4dcff`
- banner border `#ff4dff`, banner text `#ff91ff`

Plan 03 cites the older classic Monokai base (`#242424` …). The build follows the **approved override**, which is right.

The build differs in two ways:
- it repurposes `--yellow` as lavender `#f4dcff` and `--orange` as `#bb82d5` for notices
- its `--pink` is `#ff91ff`

**[proposal] M1:**
- Keep the token *values* from the mockup override.
- Add `--lavender:#f4dcff` and `--lavender-line:#5b476d` for the primary button.
- Render `.notice` like the mockup `.banner`: pink border and pink-tinted text, used **sparingly**.
- Use green only for "live/running" dots, pink for "needs you / gap", cyan for focus, links and the active tab, and yellow for inline `code` paths.
- Keep the build's 14 px base. The mockup's 13 px reads small in a daily-use tool. This is a deliberate deviation.

---

## 3. Principles for this app

1. **The conversation comes first, and the footer is the app's command line.** The selected agent's latest words, what it's running, and your draft are always visible.
2. **One chip per concern, details one click away.** Honesty stays: every limit is still visible in the coverage popover (§4.3), but it isn't repeated as paragraphs. No view shows more than one notice block at a time.
3. **Don't render controls that can't work.** Hide them, or offer a single "Open in T3 ↗" link. Never show a dashed disabled button with an explanation.
4. **New data never moves focus or scroll.** Show a "↓ new" pill instead.
5. **Local-first convenience.** Drafts survive reloads (localStorage). Paths go to the agent as plain text, since it runs on the same machine. No extra confirmations or auth layers.
6. **Everything observed is labelled "observed", not "made by".** This is cheap honesty. Don't attribute files to agents without a source-backed link.

---

## 4. Component designs

### 4.1 Footer dock (finishing M0)

Target layout at ≥ 680 px; it stays inside the main column on every tab:

```
┌─ main column ──────────────────────────────────────────────────────────────┐
│  … current view (Conversation / Activity / Artifacts / Changes) …          │
├────────────────────────────────────────────────────────────────────────────┤
│ ● Codex · gpt-5 · running   ▸ cargo test --locked          [▾ more]        │
│ “I’m reviewing the gallery layout and collecting the visual outputs…”      │  ← clamp 2 lines
│ ┌────────────────────────────────────────────────────────────────────────┐ │
│ │ [ref: p2-3d-obj-torus.webp ×]                                          │ │
│ │ Write a message…                                                       │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ To: Gallery improvements · queued for next turn      Ctrl+Enter   [Send ↑] │
└────────────────────────────────────────────────────────────────────────────┘
```

**[proposal], small changes in `fieldnotes.{html,css,js}` only:**

- **Separate the two slots.**
  - Add `#agent-state` (chip) and `#agent-activity` (current progress label) next to the existing `#latest-agent-text`.
  - `clearHistory()` must **not** touch the agent slots.
  - New function `setAgentState(kind)` with these states: `idle | running | streaming | waiting | gap | none`.
  - The latest text changes only when messages arrive, or on thread change, where it resets to "No agent message yet". On a gap, keep the text and append " · reconnecting" to the chip.
- **Activity line.** From `projection.progress`, take the last item with status `running|pending|waiting`. Render `▸ ` plus the literal `label` (CSS `text-overflow:ellipsis`, full text in `title`). If nothing is running, show nothing.
- **Agent label.** Show `provider · model` from the selected thread. Map the status chip to:
  - `streaming` when any message has `streaming:true`
  - `running` when T3 status, `activeRunId` or a running progress item says so
  - `waiting for you` when `pendingRequestCount > 0`
  - otherwise the raw T3 status word (don't invent mappings for unknown strings)
- **Expand.** A `[▾ more]` button with `aria-expanded` toggles the 2-line clamp. Esc collapses it.
- **Destination line.** Replace `#draft-help`:
  - `To: <thread title> · queued for next turn` when a thread is selected
  - `New thread in <project>` on Scratch
  - when writing is off: `Sending is off (server started read-only)` plus a **Copy draft** button that copies the draft and its references as text, so it can be pasted into T3
- **Send shortcut.** Ctrl/Cmd+Enter sends when Send is enabled. Enter inserts a newline.
- **Short status.** `#send-status` shows one short line only when there is something to say: "Sending…", "Queued in T3", "Rejected — draft kept", or "Outcome unknown — check T3 before resending". The recovery block becomes a `<details>` collapsed by default.
- **Layout.**
  - Replace `position:fixed; left:220px` with `main{display:flex;flex-direction:column;min-height:calc(100vh - 64px)}`, the active view `flex:1`, and `.conversation-dock{position:sticky;bottom:0}`.
  - Remove the ResizeObserver and `--dock-height` padding.
  - Use `max-height:40vh` with internal scroll.
  - At ≤ 680 px, hide the agent text line behind the expand toggle so the composer stays usable with a keyboard open.
  - Any equivalent fix that renders correctly is fine. The check is in §5 M0.
- **Attach.** Inspector "Add to draft" closes the dialog, stays on the current view and focuses `#draft`.

### 4.2 Conversation view (M1)

**[proposal]**

- **Message cards.** Follow the mockup: a 25 px avatar tile (initial "Y" for the user; for agents, the first letter of the provider), the name ("You" or the provider name), and a time from `createdAt` (live only; polling has none). Text in a `.msg-body` with `white-space:pre-wrap`. Fenced ```` ``` ```` blocks render as `<pre><code>` via **text nodes only**, with no HTML/Markdown injection. Show a Copy button on hover or focus.
- **Keyed rendering.**
  - Live mode: keep a `Map<id, li>`. Create rows for new IDs, update text only when it changed, remove rows whose IDs vanished.
  - Polling mode has no IDs. Re-render, but preserve `scrollTop` relative to the bottom.
- **Scroll anchoring.** If the user is within 80 px of the bottom, stick to the bottom. Otherwise show a "↓ New activity" pill, and clicking it scrolls down. Never move focus.
- **Inline tool rows, grouped by run.**
  - Backend dependency: add `runId` to the progress JSON in `live.rs:17`. It is already on `Item` and non-sensitive.
  - UI: for each `runId`, place its progress rows after that run's user message and before its assistant messages. Rows whose run is unknown go at the end, as today.
  - The ordering is labelled nowhere because it is per-run grouping, not a claim about exact interleaving.
  - A row is a one-line mono chip: `● running  cargo test --locked`. Completed rows are dimmed. Three or more consecutive completed rows collapse to "4 commands ✓ ▸".
  - Replace the "Output omitted by source" text with a small "no output" tag.
- **Status line.** `#history-status` shrinks to a one-line muted caption only when it adds something: "Showing latest 40 messages" in polling mode, or "Reconnected — some updates may be missing" after a gap. Everything else moves to the coverage chip.
- **Gap behaviour.** Do **not** clear content on a gap. Keep the last projection, dim it slightly, and show the caption above. Today the user loses everything they were reading each time the stream drops. Live data replaces it on reconnect.
- **Empty states.**
  - Scratch: "Start a new thread — type below and press Send"
  - Thread with no messages: "No messages yet"
  - T3 not configured: one sentence plus the CLI flag to set

### 4.3 Header, connection chip and coverage popover (M1)

**[proposal]**

- **Top bar.** `FIELDNOTES / <project>` · `[● Live]` chip · `Open legacy gallery ↗`. Chip states:
  - `● Live` (green)
  - `○ Polling · 15s` (muted)
  - `↻ Reconnecting` (muted)
  - `▲ Gap` (pink; stays until the next successful projection)
  - `✕ Offline` (pink)
  - `🔒 Locked` (shown on auth expiry)
- **Coverage popover.** Clicking the chip opens a small `<dialog>`/popover with a definition list. **This is where all the current disclaimer prose goes, once.**

  | Field | Value |
  |---|---|
  | Source | CLI polling, or live selected-thread stream |
  | History | Latest 40 messages, no replay |
  | Sending | On or off, with the flag name |
  | Files | Watched folders N, automatic worktree watching off, child agents not discovered |
  | Stop / answer requests | Use T3 |
- **Thread header.**
  - Line 1: title and a status chip.
  - Line 2 (muted): `provider · model · branch <branch> · <worktreePath basename>`.
  - Right side: if `pendingRequestCount>0`, a pink chip "N waiting for you"; then `Open in T3 ↗` when `link` is a usable URL.
  - **Open question:** the board does not establish what `link` contains. Verify it once against real data. If it isn't openable, omit the button.
  - Remove the disabled Stop button.
- **Remove these blocks:** `#control-note` (moved into the footer destination and the popover), the long `#destination` paragraph, the sidebar `side-note` (becomes a single "Watched folders (N) →" link), and two of the three artifacts rail paragraphs.

### 4.4 Sidebar navigation and multiple threads (M1)

**[proposal]**

- **Thread list.** Replace `<select id="threads">` with `<nav aria-label="Threads"><ul>` of buttons. Each button shows:
  - a status dot (green when running, muted otherwise; unknown statuses are muted and show the raw word in the title tooltip)
  - the title, ellipsized
  - a `•` *draft dot* when that thread has unsent text (from `session` scopes)
  - a pink count when that thread's last-read `pendingRequestCount>0` (selected thread only, since the listing has no count)
  - `aria-current="true"` on the selected thread; ↑/↓ moves between items
- **New thread.** "＋ New thread" sits at the top. It selects Scratch, focuses the dock and sets the destination to "New thread in <project>". It replaces "New thread from draft".
- **Filter.** A filter input appears above the list when there are more than 8 threads, matching on title.
- **Polling.** Keep the 15 s listing poll. Status dots for all threads give the multi-thread orchestration overview at no new cost.
- **URL state.** Use the hash `#v=<view>&t=<threadId>`, so a reload or bookmark restores the thread and tab. `changeView` and `selectThread` read and write it. An unknown thread falls back to Scratch.
- **Draft persistence.** `localStorage` key `fieldnotes:draft:<binding>:<threadId|scratch>` stores `{draft, references}`, debounced at 300 ms.
  - Clear it on a successful send, using the same exact-text rule as today.
  - **Do not** persist `uncertain`/`recovery` state beyond the tab. Simplicity beats completeness here.
  - This supersedes wiring `draft_store.rs` for now (proportionate per AGENTS.md).

### 4.5 Feedback loop: references must be sendable (M1, highest value)

**[proposal]**

- **Sending references.** When the draft has references, Send serializes them into the text body. The server and API stay unchanged (`references: []`):
  ```
  <draft text>

  Referenced files (local paths, current versions):
  - /var/tmp/fieldnotes-screens/images/p2-3d-obj-torus.webp
  ```
  The chips stay visible until send, and the destination line says "+1 file path". The agent runs on the same machine, so a path is meaningful. No bytes are uploaded and no new server code is needed.
- **Remove the block.** Delete the "Remove path references before sending" block (`fieldnotes.js:265,271-272`).
- **Copy draft.** The same serialization backs **Copy draft** when writing is off.
- **Inspector feedback.**
  - The feedback textarea keeps its per-file memory (already in place).
  - "Add to draft" appends `Re <filename>: <feedback>` to the draft, so feedback stays tied to its file in the message.
  - If the file was already referenced, it isn't duplicated (already handled by `identity`).

### 4.6 Outputs inside the conversation (M2)

All observational; no new backend.

**[proposal]**

- **Last-seen tracking.** Keep `lastSeenAt[threadScope]` as the max `item.at` seen while the Artifacts tab was open, stored in session state.
- **New-output count.**
  - On each listing refresh, `newCount` = loaded items with `at > lastSeenAt`.
  - Show it as a tab badge "Artifacts 3".
  - If the Conversation view is active, add a single inline strip above the dock: `NEW · 3 files observed in /var/tmp/… · View →`. It isn't repeated per message.
  - "View" opens Artifacts filtered to new items, with the existing kind/root filters and a "New only" toggle.
- **Live outputs rail.** At ≥ 1200 px, the Conversation view gets the mockup's right rail:
  - "Live outputs": the latest 4 thumbnails from the existing listing, each opening the inspector
  - below that, "Watching N folders · Add folder"
  - hidden below 1200 px
- **Add folder inline.** Use the existing `GET /api/dirs?prefix=` for completion and `POST /api/watch`.
  - Check whether Fieldnotes' auth client attaches the CSRF header to that POST. The route exists (`server.rs:1137`), but I haven't verified it works from the Fieldnotes page.
  - Root changes already invalidate references (`fieldnotes.js:384-392`). Keep that.
- **"Suggest output folder" button** in the rail. It inserts into the draft: "Save any images, renders or previews you want me to review under `<first watched root>`." This is just text, honest and cheap, and it directly solves "temporary outputs aren't watched".

### 4.7 Activity view: this tab session's timeline (M2)

**[proposal]**

Replace the static essay with a client-side, in-memory list, newest first, capped at 500 entries. Header line: "Since you opened this tab (HH:MM) · not saved". Entries are created when the UI observes:
- a new message ID: "You sent…" or "<Agent> replied" with a 120-character excerpt
- a progress status transition: `▸ cargo test running → completed`
- gallery `add`/`update`/`remove` SSE events: "Image observed / updated / removed", with an Inspect link if the file is still listed
- connection gaps and reconnects

Filters: All / Messages / Tools / Files. This is cheap, useful and truthful. It needs a dedup map for message IDs and progress `{id,status}`.

### 4.8 Changes view: git status and diff for the selected checkout (M2, needs a backend lane)

**[proposal], new read-only endpoint `GET /v1/changes?binding_id&thread_id`:**

- **Path.** Use the selected thread's validated `workspace_observation.canonical_path`, or `worktreePath` once validated by `workspace_discovery::discover`. Never use a path supplied by the browser.
- **Commands.** Run `git -C <path> status --porcelain=v2 --branch` and `git diff --numstat`. Run `git diff -- <file>` on demand per file, capped at 256 KiB, with a 5 s timeout.
- **Response.** `{branch, ahead, behind, files:[{path,status,adds,dels}], truncated}`.
- **UI.**
  - A file list with M/A/D/?? tags and +/− counts.
  - Clicking a file expands its unified diff in a `<pre>`, coloured per line by prefix in text nodes.
  - A Refresh button; auto-refresh when the agent's run finishes (the status chip goes from running to anything else).
  - If no checkout is known: one line, "No checkout known for this thread."

This is the earlier plans' "basic checkout-scoped diff". For a personal local app, running git read-only in the thread's own checkout is a proportionate risk.

### 4.9 Multiple agents (M3, needs child discovery)

**[proposal]**

- **Data.** Child discovery depends on the backend lane wiring `t3_mcp.rs` `t3_thread_list(includeSubagents:true)`. The listing gains `parentThreadId` and `relationship` (`subagent`/`fork`). Until that exists, **render nothing** for agents. Keep just one line in the coverage popover ("Child agents: not discovered").
- **Sidebar.** Child threads indent under their parent, e.g. `↳ Material studies ●`, collapsed by default with the parent showing a count "2 working". Selecting a child is just selecting a thread: the conversation, footer and drafts all follow, because a child *is* a T3 thread.
- **Footer agent switcher.** When the selected thread has children, the footer label becomes a small menu: `● Parent · running ▾ → Material studies · running / Lighting check · done`. Choosing one selects that thread. This is the "active agent message" in multi-agent form.
- **Agents rail block** on Conversation (≥ 1200 px), per the mockup: one row per child with status and an "Open" link.
- **"Ask parent to delegate".** Inserts template text into the draft ("Please delegate a focused sub-task: …"). Honest, because it's just a message.
- **Not planned:** fake orchestration controls, or attributing files to children from timing.

### 4.10 Media breadth and temporary outputs (M4)

**[proposal]:**
- **Backend kinds.** Add `Video` (mp4/webm/mov) and `Audio` (wav/mp3/ogg/flac) to `item.rs` `Kind`, add Range support to `/f/` (`206 Partial Content`), and render previews with `<video controls preload=metadata>` and `<audio controls>`.
- **Code/text.** A 64 KiB text preview, after an encoding sniff. The Inspector inventory documents a binary-`.txt` crash; reject non-UTF-8.
- **Keep copy.** `POST /api/keep?id` copies the current file to `~/.local/share/live-gallery/kept/YYYY-MM-DD/<name>` and returns the new path. It is listed as its own watched root, "Kept". This solves temp files vanishing before review, and copying bytes the user explicitly asked to keep is proportionate.
- **Inspector page.** Turn the inspector into an in-page panel per the mockup: Back to origin, a Details rail, prev/next, and, for kept copies, compare (image slider or side-by-side).

### 4.11 State catalogue: one sentence each, no essays

| State | Where | Copy | Action |
|---|---|---|---|
| T3 not configured | Conversation empty | "Not connected to T3. Start with `--t3-executable …`." | none |
| Scratch selected | Conversation empty | "New thread — type below." | focus draft |
| Polling | chip | "Polling · 15s" | popover |
| Live | chip | "● Live" | popover |
| Gap | chip + caption | "Reconnected — some updates may be missing." | — |
| Locked / expired | chip + banner | "Session locked. Reload to unlock." | Reload |
| Sending off | footer | "Sending is off (server read-only)." | Copy draft |
| Sending | footer | "Sending…" | — |
| Queued | footer | "Queued in T3." (auto-hides after 5 s) | — |
| Outcome unknown | footer | "Outcome unknown — check T3 before resending." | Open in T3 |
| Requests waiting | header chip, footer state | "N waiting for you" | Open in T3 |
| Agent running a command | footer | "▸ <label>" | — |
| No watched folders | Artifacts | "No folders watched." | Add folder |
| Indexing | Artifacts caption | "Indexing…" | — |
| File gone | Inspector | "This file is gone or changed." | Close |
| No checkout | Changes | "No checkout known for this thread." | — |

---

## 5. Milestones (prioritized), dependencies and lightweight checks

The ordering gives the **first everyday-usable slice = M0 + M1**: you can pick threads, read a calm conversation, see what the agent is doing in the footer, send messages and file feedback to it, and survive reloads.

Shared rules:
- **Ownership:** all milestones are UI-only (`assets/fieldnotes.*`, `tests/fieldnotes*.cjs`) unless marked **[backend]**.
- **Checks:** keep them to a few focused `node --test` DOM cases per milestone, plus one render check by the controller. No new suites.

### M0: finish the always-visible footer (≈ ½ day). Dependency: none
- Scope: §4.1 in full, built on top of the uncommitted change. Commit it first as-is if the controller wants a checkpoint, then the fixes.
- Checks:
  1. DOM test: after `clearHistory('Live gap…')`, `#latest-agent-text` still holds the last assistant text.
  2. DOM test: a projection with a `running` progress item shows its label in `#agent-activity`; once that item completes, `#agent-activity` is empty.
  3. DOM test: Ctrl+Enter triggers submit only when `#send` is enabled.
  4. Controller render, 1440×900 and 390×844, on Conversation and Artifacts tabs: the footer is visible, the last card/message is not hidden behind it, and no horizontal scroll appears.

### M1: calm conversation and navigation (≈ 2–3 days). Dependencies: one tiny **[backend]** change, `runId` in the progress JSON (`live.rs:17`), plus a one-time check of what `link` contains
- Scope:
  - §4.2: cards, keyed render, scroll anchoring, run grouping, gap keeps content
  - §4.3: chip, popover, header, removing the disclaimer blocks
  - §4.4: sidebar list, draft dots, hash state, localStorage drafts
  - §4.5: references inlined into the message
  - §2.2: token alignment
- Checks:
  1. DOM test: two projections with the same message IDs keep the same `<li>` nodes (identity preserved) and don't change `scrollTop` when the user isn't at the bottom.
  2. DOM test: a draft with one reference sends a body containing "Referenced files" and the path, with `references: []`.
  3. DOM test: draft text survives a simulated reload through localStorage, and clears after an accepted send.
  4. DOM test: progress with `runId` R renders after the user message of run R.
  5. Controller: one real (or fake-ACP) turn in the browser; the footer shows streaming/running state, then the reply; the screenshot shows at most one notice block per view.

### M2: outputs, activity and changes in the loop (≈ 3 days). Dependency: **[backend]** `/v1/changes` (§4.8); confirm the CSRF path for `/api/watch` from Fieldnotes
- Scope: §4.6 (new badge, strip, rail, add folder, suggest folder), §4.7 (session timeline), §4.8 (changes UI), and inspector prev/next with ←/→.
- Checks:
  1. DOM test: three gallery `add` events plus a listing with newer `at` give "Artifacts 3"; opening Artifacts resets the count.
  2. DOM test: the timeline dedupes repeated projections, so the same message ID creates one entry.
  3. Rust test **[backend]**: a temp git repo with one modified and one untracked file returns correct `files`, and a path from the request is ignored.
  4. Controller: render the Changes view against a real worktree.

### M3: multiple agents (≈ 2 days UI after the data exists). Dependency: **[backend]** child listing via MCP with `parentThreadId`/`relationship`. Runtime proof is still open on the board (lineage runtime research is incomplete)
- Scope: §4.9.
- Checks:
  1. DOM test: a listing with a parent and two children renders nested, and selecting a child switches the conversation and footer.
  2. Controller: a populated family in an isolated T3, which is the board's open gate.

### M4: media breadth, kept copies and the inspector page (≈ 3–4 days). Dependency: **[backend]** Kind/Range/keep endpoint
- Scope: §4.10.
- Checks:
  - a Range request returns 206 with the correct bytes
  - a non-UTF-8 `.txt` shows "Preview unavailable" without throwing
  - a kept copy appears under "Kept"
  - Controller: play one mp4 and one wav

### Deferred until T3 capability is proven
These are not designed further here:
- in-app Stop, interrupt, force or background
- answering approvals or questions in-app (use "Open in T3" until then)
- revision history and compare for non-kept files
- the timeline scrubber
- the ⌘K palette

---

## 6. Contracts requested from other lanes (small, concrete)

1. `src/server/live.rs:17`: add `"runId": i.run_id` to each progress entry. It is non-sensitive and enables §4.2 grouping. **Required for M1.**
2. Thread detail `link`: confirm its format at runtime. If it's an openable T3 URL, the UI will use it for "Open in T3". **Needed for M1.** Without it, the button is omitted.
3. `GET /v1/changes`: §4.8 shape. Read-only; the path comes from server-side validated thread workspace only. **M2.**
4. `/api/watch` and `/api/dirs` callable from the Fieldnotes page with the same session cookie and CSRF as `/v1/*`. **M2.**
5. Listing with `parentThreadId`, `relationship` and `status` for child threads (MCP `includeSubagents:true`). **M3.**
6. `Kind::{Video,Audio}`, Range on `/f/`, and `POST /api/keep`. **M4.**

## 7. Explicit non-goals (to stay unbloated)
- No per-message disclaimers, and no visible paragraph repeated in more than one place.
- No placeholder panels for features with no data. Activity and Changes get real content in M2; until then they show a one-line empty state.
- No new auth, permission prompts or confirmation dialogs beyond what exists. Do not add confirm-to-send.
- No server-side draft store for now; localStorage is enough.
- No Markdown/HTML rendering of agent text beyond text-node code fences.

## 8. Verified vs. proposed, at a glance
- **Verified (source):**
  - the footer change and its defects (§1.2)
  - the data the UI already receives but ignores (`pendingRequestCount`, `branch`, `worktreePath`, `link`, `createdAt`, `runId` on messages)
  - references are rejected by the server and blocked by the UI
  - kinds are limited to Image/Model
  - no Range support
  - `draft_store` is not wired
- **Verified (runtime, board):** real Codex message and command-progress delivery through `/v1/live/selected`. Browser rendering of it is **not** verified, and token-level streaming is **not** proven.
- **Proposed:** everything in §4 and §5. Unverified dependencies: the contents of `link`, the CSRF path for `/api/watch` from Fieldnotes, child listing at runtime, and the `/v1/changes` endpoint.
