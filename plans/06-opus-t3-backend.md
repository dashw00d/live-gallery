# 06 — Closer T3 backend integration for a personal local harness (Opus research lane)

Date: 2026-11-15. Author: Opus research lane (planning only; no application edits, no tests or services run by this lane).
Inputs: `/home/ryan/dev/live-gallery/AGENTS.md`, board `/home/ryan/dev/live-gallery-agents/BLACKBOARD.md` (read through "Planning review — UI and T3 integration"), plans 01–04, integration tree `/home/ryan/.t3/worktrees/live-gallery/t3-2c3d524f-0aad681690c6ab7b` at `0b118cf` plus its uncommitted footer diff, runtime reports `/var/tmp/gallery-real-wave15/report.json` and `/var/tmp/gallery-real-wave16/report.json` (and their `run.py`), pinned T3 source `/var/tmp/t3code-integration-research` at `86dbf2ab`.

## Evidence labels

- **[RT]** Verified at runtime on the installed T3 v0.1.9 (protocol 2, migration 81) in an isolated base. I took this from retained reports or board entries; I did not re-run anything.
- **[TREE]** Present in integration-tree code. Pass counts are as reported on the board; this lane did not re-run them.
- **[SRC]** Present in pinned upstream source `86dbf2ab` only. Installed 0.1.9 is build `24e77473ecf4`, which differs, so nothing here is installed behaviour until tested.
- **[P]** This plan's proposal. Not implemented and not verified.

---

## 1. Bottom line

1. **Use T3's own environment RPC (the WebSocket protocol T3's web UI uses) for both streaming and control.** Drive it through the existing pinned Node sidecar, extended with a small fixed `dispatch` operation. The installed runtime has already proven every primitive the first usable slice needs: subscribe, create a thread, dispatch a message and interrupt an exact run. Today, though, only the subscribe path goes through the product. The writes were all made by test runners. **[RT + P]**
2. **Use the T3 CLI only for bootstrap**: find the server, issue and revoke one local session, and list projects. Stop using it as the conversation control plane. It has no stream, no interrupt, stop, steer or queue, and no children, and it mints a new full-access MCP session on every call. **[RT/SRC]**
3. **MCP is optional and comes later.** Use it only for conveniences that are awkward over RPC, such as launching a thread in a new worktree. Skip the OAuth consent flow for local use: pinned source accepts a CLI-issued `mcp-client` bearer. That is **[SRC]** only and needs one quick installed check.
4. **No upstream patch or fork is needed for the first slices.** The wanted patches are either already in newer upstream (the force-stop successor guard) or only matter if we keep wrapping the CLI. Track upstream versions and gate each feature per version instead.
5. **Remove most of the security scaffolding.** The integration stack checks the session again on every release, caps a stream at 25 s, needs a separately enrolled 0600 credential file plus about 20 startup flags, and uses fail-closed reducer gaps. That is enterprise-grade for a single-user loopback app, and the fail-closed reducer caused the Wave 12–14 "no assistant output" failures. Keep loopback binding, an Origin/CSRF check and resource bounds. Drop the rest (§7).

---

## 2. What is actually proven today

### 2.1 Installed-runtime facts [RT]

| Capability | Evidence | Path used |
|---|---|---|
| Product live endpoint streams a real Codex turn: user message, command `running`→`completed` (`outputOmitted:true`), final assistant message; no gaps | Wave 15 (28 projections, assistant after about 8.3 s); Wave 16 (`progress` running/completed). `liveGapDiagnostics: []` in both | **Product** `/v1/live/selected` ← Rust supervisor ← sidecar `subscribeThread` |
| Thread listing via product (`/v1/threads`) on a populated real project | Wave 15/16 `threadListed:true` | Product → CLI `thread list` |
| `orchestration.dispatchCommand` `thread.create` (with `modelSelection {instanceId:"codex", model, options}`, `runtimeMode`, `worktreePath:null`) and `message.dispatch` `{dispatchMode:{type:"start_immediately"}}` with real Codex, 1–2 turns, file written and verified | Waves 11–16 `run.py` lines 98 and 148 | **Test runner** using the wave 5 private RPC probe with an `orchestration:operate` session. **Not the product.** |
| `run.interrupt {threadId, runId}` on an exact run reaches the `interrupted` terminal | Wave 9 fake-ACP `run_installed.py:97`, six gates | Test runner RPC probe, fake provider |
| Snapshot, reconnect replay and future-cursor snapshot fallback; live metadata tail; revoked session → new ticket gets HTTP 401 | Wave 5 seven gates; Wave 8 | Sidecar/probe |
| An already-open socket keeps delivering after its session is revoked | Wave 8 | Sidecar |
| Read-only MCP over OAuth: initialize, 68 tools, project list/read, empty thread list, revoke → 401 | Waves 4 and 6 | Rust `t3_oauth` + `t3_mcp` in a private harness. Not wired into the product. |
| Local bootstrap: `t3 project add`, `t3 serve --base-dir … --no-browser`, and `t3 auth session issue --scope … --ttl … --json` work on a private base | Wave 3; runners | CLI |
| Codex message updates arrive **finalized** (`streaming:false`), as a separate preface and final message. No token deltas. Fake ACP shows full-text replacements at about 1 s spacing | Waves 11 and 15 | — |

### 2.2 Proven in the tree but not end-to-end with a real provider [TREE]

- Product **create and send** use CLI `thread start` / `thread send` (`src/t3_adapter.rs:257-258`) behind `--t3-allow-write`. These were exercised only with a fake CLI (Wave 7 browser test). **No real provider turn has ever been started from the product's own create/send path.** This is the biggest hole in "normal conversation".
- The live stream (`src/server/live.rs`) runs `read_ephemeral(…, 25 s …)`. It checks the source session again on each release, allows at most 2 streams, and the UI reconnects up to 3 times (Wave 12). The projection carries messages and progress only.
- `workspace_discovery::discover` validates the selected thread's worktree as a *candidate*, with `auto_watch:false`. Nothing is watched automatically.

### 2.3 Uncommitted footer changes in the integration tree (inspected, not touched)

`assets/fieldnotes.{html,css,js}` (+26/−3) moves the composer out of `#conversation` into a fixed `footer.conversation-dock`, so it shows on every view. It also adds a "latest agent message" strip, `renderLatestAgent()` (fed by both the live and polling paths), and a `ResizeObserver` that sets `--dock-height`. Risks:

- `left:220px` is hard-coded to the sidebar width.
- DOM tests that assume the composer sits inside `#conversation` might need updating. I did not run them.
- `clearHistory()` writes status and gap text into the agent strip. Plan 05 rightly flags that this shows system text labelled as "Agent" and erases the last real agent message on reconnect.

Plan 05's M0 fixes these issues. This change is a prerequisite for "attach artifact from Artifacts view, then send", so it should be committed first (M0, owned by plan 05).

### 2.4 Present in pinned source only, not installed-verified [SRC]

- **Command types:** `orchestrationV2.ts:3077-3640` defines these `dispatchCommand` types: `thread.stop`, `run.interrupt {holdQueue?}`, `message.dispatch` with dispatch modes `steer_active{targetRunId}`, `restart_active{targetRunId}`, `queue_after_active`, `start_immediately` and `defer_start{workspaceStrategy?}`, plus `freshContext` and `attachments: ChatAttachment[]`. Also `queued-run.{start,reorder,cancel,edit}`, `queue.resume`, `queued-message.promote-to-steer`, `runtime-request.respond {decision?, answers?, feedback?}` (approvals and questions), `subagent.stop {runId, subagentId}`, `thread.fork`, `provider.switch`, `thread.model-selection.set` and `thread.runtime-mode.set`. **`delegated_task.request` needs `parentRunId`/`parentNodeId`**, so it is meant for provider-originated delegation and is not a clean user entry point.
- **Force stop:** `orchestration.forceStopThread {threadId, runId}` is a separate RPC that needs `orchestration:operate`. Wave 7 found that the installed build lacks the newer successor guard, so force stays gated (§6).
- **Server discovery:** server state file is `<baseDir>/userdata/server-runtime.json` with an `origin` (`config.ts:174`, `cli/thread.ts:225-229`). The user's real `~/.t3/userdata/server-runtime.json` **exists**. I only checked existence and did not read it.
- **MCP auth:** `/mcp` accepts any bearer session with subject `mcp-client` and method `bearer-access-token` (`EnvironmentAuth.ts:1524-1545`). `t3 auth session issue` has a `--subject` flag (`cli/auth.ts:67,251`), so an MCP token can presumably be issued locally without OAuth.
- **Attachments:** the upload route is `/api/attachments/upload` (`assets/AttachmentUpload.ts:36`).
- **Lineage:** `projection.subagents[]` and the `subagent.updated` event carry child thread IDs (board, Wave 10 worktree-design).

### 2.5 Host-session observation (not installed proof)

This planning session's own T3 MCP toolset exposes tools such as `delegate_task {isolation:"worktree"}`, `t3_thread_launch {workspaceStrategy}`, `t3_thread_send {mode: auto|queue|steer|restart}`, `t3_thread_interrupt {runId?, stop?}`, `task_cancel` and `t3_attachment_prepare_upload`. I only read their schemas and called none of them. They show T3's intended agent surface. They do not prove that an external client of installed 0.1.9 gets the same tools or behaviour.

### 2.6 Evidence caveats found while reading

- The Wave 16 report lists `cleanupEscalatedPids:[2068943]` and `remainingGroups:[2068838]`. So cleanup needed SIGKILL escalation, and one group was still signalable when checked. Both PIDs are gone now. This is a little weaker than the board's "cleaned".
- The Wave 15/16 `sourceHashes` record only the runner, bridge and probe hashes, **not the product binary or commit**. The binary path `/var/tmp/gallery-real-wave12-private/target/debug/live-gallery` was rebuilt again at 22:53, after Wave 16. "Built committed dde5af5" is the controller's statement and is not recorded in the report. Future runners should record the commit and binary hash.

---

## 3. Options evaluated

| Option | Proven | Missing / cost | Verdict |
|---|---|---|---|
| **A. Wrap the CLI** (status quo for control) | list, show, start, send on installed. Text through stdin. | No stream, interrupt, stop, steer, queue, approvals, children or attachments. No caller retry key. Mints and revokes a full-access MCP session and mounts the AppImage on every call. The installed `--wait` does not follow wakes. Real-provider start/send from the product has never run. | Bootstrap only: session issue/revoke, project list, and a fallback list/read when RPC is down. |
| **B. Environment RPC through the pinned sidecar** (T3 web UI's protocol) | subscribe/snapshot/replay/live (product path, real Codex); create, dispatch and interrupt (runner path). One token covers all of it. | The sidecar is read-only today (`core.mjs` ops: configure/subscribe/ackCommitted/cancel/reconnect/close). Needs a fixed `dispatch` op. Protocol is a compatibility commitment, not a public SDK. Pinned contracts are newer than installed. | **Primary plane for stream and control.** |
| **C. External MCP** | Read-only OAuth runtime path. | Writes untested. No stream. The OAuth consent dance is heavy for local use. `t3_background_wait`/`delegate_task` are designed for in-provider callers, and external use is unverified. | Optional, later, for launch-in-worktree or other MCP-only conveniences. Use a CLI-issued `mcp-client` token [SRC], not OAuth. |
| **D. Small upstream T3 patch** | — | Needs building T3 yourself or upstream acceptance, then a rebase burden. Wanted items: CLI `thread interrupt/stop`, `--include-subagents`, a public NDJSON `thread watch`. All are unnecessary if B is used. The force successor guard already exists in newer source. | Not needed. File upstream issues for a documented stream API and CLI parity. Revisit only if B breaks across upgrades. |
| **E. Native Rust Effect-RPC client** (drop Node) | — | Reimplements framing, ticket auth, frame parts and schemas. | Defer. The sidecar works. Revisit after two T3 upgrades have shown which parts churn. |
| **F. Read T3 SQLite/logs** | — | Unsupported, racy, leaks secrets. | Reject. |

---

## 4. Target architecture [P]

```text
 live-gallery (Rust, 127.0.0.1)
  ├─ bootstrap (CLI, once):  t3 auth session issue --scope orchestration:read --scope orchestration:operate --ttl 12h --json
  │                          origin ← <base>/userdata/server-runtime.json ; env ← /.well-known/t3/environment
  ├─ one Node sidecar (existing bridge, + `dispatch` op)  ── /ws Effect RPC ──►  user's T3 server
  │     subscribe(thread) ×≤8   dispatch(fixed allowlist)   forceStop (gated)
  ├─ reducer (lenient)  → per-thread projection: messages, progress, runs, queue, requests, children, worktreePath
  ├─ watcher: manual roots  ∪  auto roots {selected worktree, child worktrees, project root, media/temp dirs}
  └─ HTTP/SSE + Fieldnotes UI (composer dock on every view)
 exit: t3 auth session revoke <id>
```

- **One credential**, minted at startup from the user's own CLI as the machine owner. It stays in memory, goes to the sidecar over stdin and is revoked on exit. No credential file and no enrollment step.
- **One sidecar process** for all subscriptions and dispatches. This keeps the verified 8-subscription and frame limits.
- **Commands are a fixed allowlist** mapped from UI intents. The browser never sends raw RPC.
- The T3 deep link stays visible as the escape hatch for anything not yet wired, such as approvals in early milestones.

---

## 5. Capability matrix

| User capability | Mechanism | Status | Milestone |
|---|---|---|---|
| See threads, select, read history | CLI list/show today; switch to sidecar shell/thread snapshot | RT (CLI), RT (snapshot) | M1 |
| Live user-visible events (messages, command/tool status) | `subscribeThread` → reducer → SSE | **RT (product)**. Token streaming for Codex is **not observed**. | M2 hardens |
| New thread with provider/model | `thread.create` + `message.dispatch start_immediately` | RT (runner), product path missing | M3 |
| Follow-up turn / queue while busy | `message.dispatch queue_after_active` | SRC (`start_immediately` is RT) | M3 |
| Steer mid-turn | `message.dispatch steer_active{targetRunId}` | SRC | M3 |
| Stop this run | `run.interrupt {runId}` | RT (fake ACP) | M3 |
| Stop thread (hold queue, stop delegates) | `thread.stop` | SRC; older peers may downgrade it to a plain interrupt (Wave 7) | M6 |
| Force kill a stuck run | `forceStopThread` | SRC + **known installed race** | M7, gated |
| Background work | display `run.background-work-cancelled`/node state; no launch mode exists | SRC; no general background-execution command found | M7 (display only) |
| Approvals / questions | `runtime-request.updated` → `runtime-request.respond` | SRC; untested | M5 |
| Subagents / children | `projection.subagents`, `subagent.updated`, child subscribe; `subagent.stop` | SRC; installed populated family **unverified** (lineage lane) | M6 |
| Choose provider/model | `modelSelection` on create; `thread.model-selection.set` | RT for `codex`; listing available providers is unverified | M3 (fixed list from config), later from shell snapshot |
| Auto-watch the selected worktree | `worktreePath` from snapshot → auto root | SRC field + TREE candidate validation; watching missing | M4 |
| Auto-watch child worktrees | child snapshots' `worktreePath` | SRC | M6 |
| Media/temp artifacts | configured media/temp dirs as auto roots | P | M4 |
| Attach artifact to a draft | path reference in text (works now); image upload `/api/attachments/upload` → `attachments` | TREE (references blocked from send today); SRC upload | M4 (text refs), M8 (bytes) |
| New thread in its own worktree | `defer_start{workspaceStrategy}` or MCP `t3_thread_launch workspaceStrategy:"worktree"` | SRC / host-only | M8 |

---

## 6. Scoped stop / force / background, the simple and safe version [P]

- **Stop (default button):** `run.interrupt` on the exact `runId` shown, never "newest". Show "stopping…" until the authoritative `run.updated` terminal arrives. The request receipt is not termination.
- **Stop thread:** a separate, explicitly labelled menu item mapped to `thread.stop`. Enable it only after one installed check confirms that queued messages are held and not dropped.
- **Force:** hidden behind a confirmation. Enabled only when the thread has **no queued successor**, which is a cheap client-side guard against the installed successor race. Show the returned `outcome` (`killed|released|releasing|shared`) verbatim. Do not use an OS-kill fallback.
- **Background:** display only, as "agent reports background work" plus T3's own state. Do not invent detach or launch.

---

## 7. Startup and configuration simplification [P]

**Today [TREE]:** about 20 flags (`--t3-executable --t3-base-dir --t3-project --t3-home --t3-cwd --t3-search-path --t3-allow-write --t3-bridge-node --t3-bridge-bundle --t3-bridge-cwd --t3-bridge-endpoint --t3-bridge-environment --t3-bridge-credential-file --t3-workspace-ancestor …`). It also needs a separately enrolled 0600 credential file, an isolated HOME and a cleared environment.

**Target:** `live-gallery --t3` with defaults:

| Setting | Default | Override |
|---|---|---|
| T3 launcher | `~/.t3/bin/t3`, else `t3` on PATH | `--t3-bin` |
| Base dir | `~/.t3` | `--t3-base-dir` |
| Origin | `<base>/userdata/server-runtime.json` `.origin` | `--t3-origin` |
| Environment | `/.well-known/t3/environment` (check protocol = 2) | — |
| Credential | issued at startup, read+operate, 12 h TTL, revoked on exit | `--t3-token-file` (reuse) |
| Project | all projects, chosen in the UI | `--t3-project` |
| Writes | on (a personal app). `--read-only` to disable | — |
| Node / bundle | `node` on PATH, bundle embedded or next to the binary | `--t3-node` |
| Auto-watch allowlist | project roots + `~/.t3/worktrees` + configured media dirs | `--watch-allow` |

Keep the old flags as hidden aliases for one release so the test runners keep working.

**Keep:** the 127.0.0.1 bind, a per-launch random cookie, the Origin check on POST, bounded queues and frame sizes, message text via stdin (never argv), no tokens in logs, and session revocation on exit.

**Drop or relax:**

- Per-release `/api/auth/session` revalidation: check once at configure and on each reconnect.
- The 25 s stream lifetime and 3-retry budget: use one long-lived subscription with reconnect.
- The 0600 credential file, inode and owner checks.
- The bundle SHA manifest check at every probe: check once at startup.
- Fail-closed whole-stream gaps on unknown or malformed entities (§8).
- The `--t3-allow-write` opt-in.
- The cleared/isolated HOME for the user's own T3: the user's own CLI with their own HOME is the intended path.

Isolated bases remain for automated tests only.

---

## 8. Compatibility and versioning [P]

- At startup, record `{serverVersion, orchestrationProtocolVersion, databaseMigration}` from the descriptor and show it in the UI footer. Require protocol = 2. For any other `serverVersion`, warn and run with only the **verified-on-this-version** command set.
- Keep a small static table `capabilities[version] = {create, dispatch.start, dispatch.queue, dispatch.steer, run.interrupt, thread.stop, respond, subagent.stop, forceStop}`. Each entry flips to on only after a recorded runtime check (§10). Unknown versions inherit the read-only set plus `run.interrupt`.
- **Lenient reducer:** ignore unknown event types and unknown fields. If one entity fails to parse, drop that entity and bump a visible "N unsupported updates" counter. Do not tear down the stream. Reserve real "gap" for transport loss or sequence discontinuity, and resubscribe with a fresh snapshot then. Wave 14's `runtimePolicy.enforcement:"native"` failure is exactly the class of break this prevents.
- The sidecar is built from pinned `86dbf2ab` contracts and the installed build is `24e77473ecf4`. When T3 is upgraded, re-run the M1–M3 smoke check before turning on new commands. Rebuild the sidecar from the matching T3 tag when one is available.

---

## 9. Milestones (prioritised, incremental)

Each milestone is one writer in the integration tree, uses focused tests only, and ends with **one** bounded real-provider or fake-ACP check in an isolated base unless noted. The user has authorized bounded signed-in provider tests (board, Wave 12). Every runner should record the commit and binary hash.

**M0: land the dock.** Commit the uncommitted footer change (the owner reviews `left:220px` and mobile). Check: existing `node --test tests/fieldnotes*.test.cjs` passes, and one screenshot of each view with the dock. Dependencies: none.

**M1: one-flag startup and one token.** Add bootstrap (§7) and session issue/revoke. Pass the token to the existing sidecar over stdin and drop the credential-file requirement. Keep old flags as aliases. Checks:
- (a) **Installed gate:** `t3 auth session issue` works while the server is running, on a disposable base. Unverified today; runners issued sessions before `serve`.
- (b) `live-gallery --t3 --t3-base-dir <disposable>` lists threads and attaches a live stream.
- (c) After exit, `t3 auth session list` shows the session revoked.
- (d) One unit test for runtime-state parsing.

Dependencies: none.

**M2: steady stream.** One long-lived subscription per selected thread, reconnect through sidecar `reconnect` and fresh snapshot, lenient reducer (§8), and the projection adds `runs` (id, status) and `worktreePath`. Checks:
- (a) The existing full 82-frame fake replay still passes.
- (b) A synthetic unknown event or field does not gap.
- (c) One real Codex two-turn run with the stream held for at least 60 s and no reselect.

Dependencies: M1.

**M3: real conversation control (top priority after M1).** Add a sidecar `dispatch` op with a fixed allowlist: `thread.create`, `message.dispatch` (`start_immediately`, `queue_after_active`, `steer_active`) and `run.interrupt`. Use the UI attempt UUID as `commandId`. Product create/send move from CLI to RPC, and the CLI path stays as a fallback. UI: Send (auto-chooses start or queue from run state), Steer, Stop run, plus a provider/model picker from a configured list. Checks:
- (a) Sidecar unit test: unknown op or command rejected.
- (b) Fake ACP: create → turn 1 → queued turn 2 while busy → interrupt the exact run.
- (c) Real Codex, all through product endpoints: create, second turn, one steer. Record whether steer is accepted on 0.1.9.
- (d) Find out whether a repeated `commandId` is deduplicated, and record the answer. Do not assume it.

Dependencies: M1. M2 is preferred but not required.

**M4: automatic artifacts for the selected thread.** Auto roots come from the selected thread's `worktreePath`, else the project root, plus configured media/temp dirs. They are additive, not persisted and deduplicated by canonical path, and accepted only under the allowlist (§7). Skip symlinks and use the existing watcher. Do not use openat2 or the descriptor-anchored redesign. The Artifacts view groups cards by root ("selected worktree", "media"). Draft attachments go in as path references inserted into the text, with the current send block lifted. Checks:
- (a) Two unit tests: allowlist accept/reject, and switching threads removes the old auto root while manual roots survive.
- (b) In the fake or real run from M3, a file the agent writes appears as a card within the poll interval.
- (c) Attach that card to the draft and send it as text.

Dependencies: M2 (`worktreePath`). Can run in parallel with M3.

**M5: approvals and questions.** Project `runtime-request.updated` into a pending-request card and answer with `runtime-request.respond`. Create threads with `runtimeMode` chosen by the user (default stays the project default). Checks:
- (a) Extend the fake ACP agent to request permission once. Expect one approve and one deny round trip.
- (b) One real Codex `approval-required` run with one approval.

Dependencies: M3.

**M6: subagents, child worktrees, thread stop.** Read `projection.subagents`, subscribe children (cap 7 alongside the selected thread) and show a child list with status. Add each child's `worktreePath` as an auto root (M4 mechanism). Add `subagent.stop` and the `thread.stop` menu item. Checks:
- (a) Fixture reducer test for the subagent edge.
- (b) **Installed gate:** one real Codex run whose prompt asks the agent to use T3 `delegate_task` with worktree isolation. The child appears, a file in the child's worktree appears as an artifact, and stopping the child works. This is the first populated-family runtime proof; the lineage lane left it unverified.
- (c) `thread.stop` holds the queue.

Dependencies: M2, M4.

**M7: queue editing, force, background display.** Use `queued-run.{edit,cancel,reorder}` and `queue.resume` for the queue panel. Force goes behind the §6 guard. Background state is display only. Check: fake ACP queue edit and cancel, plus force on a fake run with an empty queue showing the outcome. Do not test force with a queued successor on 0.1.9; it stays disabled in that state.

Dependencies: M3.

**M8 (optional): bytes and worktree launch.** Image attachments via `/api/attachments/upload` → `attachments[]`. "New thread in new worktree" via `defer_start{workspaceStrategy}` if 0.1.9 accepts it from a client, else MCP `t3_thread_launch` with a CLI-issued `mcp-client` token [SRC gate]. Check: one image delivered to a fake ACP turn, and one worktree-launched thread with its root auto-watched.

**Order:** M0 → M1 → M3 → M2 (M4 in parallel) → M6 → M5 → M7 → M8. Conversation control comes before stream hardening because streaming already works and product-originated turns do not.

---

## 10. Lightweight acceptance discipline

- One focused unit or fixture test per new contract, plus **one** isolated runtime run per milestone. Avoid new security test suites. The existing ones can shrink when the relaxed rules in §7 land, and the writer should delete tests that only assert removed limits.
- Runtime runners record `{product commit, binary sha256, T3 descriptor, cleanup}` and count success only from product-endpoint observations, not from provider completion. Wave 12/13 showed `success:true` while the product failed.
- Capability flags (§8) flip on only after the matching runtime check is noted on the board.

---

## 11. Open questions and risks

1. Does `auth session issue` against a **running** server's base work on 0.1.9 without SQLite contention? This gates M1. Fallback: OAuth-less `--t3-token-file` that the user mints once.
2. Does 0.1.9 accept `steer_active`, `queue_after_active` and `thread.stop` from an environment-RPC client, and does it deduplicate `commandId`? Answered in M3/M6.
3. Does installed 0.1.9 populate `projection.subagents` and child `worktreePath` for provider-initiated `delegate_task`? Answered in M6. Until then, child coverage is "unknown", not "none".
4. Codex on 0.1.9 delivers finalized messages. "Streaming" for Codex means item-level progress (command running/completed) plus a final message. Don't promise token streaming; fake ACP shows replacement updates are possible when the provider emits them.
5. Coupling to the protocol: the RPC/contracts are T3-internal and can change between releases. That is accepted for a personal tool, and the version table (§8) plus the M1–M3 smoke check on upgrade keep it honest.
6. Security relaxations (§7) assume a single-user machine and a loopback bind. A hostile same-UID process is out of scope by design, as it already effectively is.

## 12. Reconciliation with plan 05 (UI lane)

- **Shared:** M0 (footer, owned by 05). References are sent as an inlined text block with `references: []`, which matches 05 and needs no server change. "Open in T3" is the fallback for controls that are not wired yet.
- **Backend items 05 asked for that fit here:**
  - `runId` on progress rows → M2 projection (`runs` + `runId`).
  - Check what `link` contains → note during the M1 runtime check.
  - Read-only `/v1/changes` → separate small item after M4. It does not depend on T3.
- **One difference: child listing.** 05 proposes MCP `includeSubagents:true`. This plan prefers RPC `projection.subagents` (M6) on the same single token, which avoids the OAuth/MCP setup. Both are [SRC] only. Whichever M6 proves on 0.1.9 wins, and the UI contract (children with status and worktree) is the same either way.

## 13. Explicit non-claims

This lane started no T3 server, provider, browser, test, subagent or service. It did not read the user's T3 state beyond confirming that `~/.t3/userdata/server-runtime.json` exists. It did not edit the integration tree, existing plans or user files. All [SRC] and [P] items above are unverified on installed 0.1.9.
