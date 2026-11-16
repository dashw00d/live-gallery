# Streaming coding harness: product and implementation roadmap

Status: planning, 2026-11-15. This is a proposed build, not a working implementation. Read alongside [T3 integration](02-t3-integration.md), [feed and UX](03-feed-and-ux.md), and [execution and validation](04-execution-and-validation.md). Upstream source research pins T3 Code commit `86dbf2abd18e631da1061f3a2489da603b2cc242`; installed versions and live integration remain untested.

## Product promise

An everyday coding harness with normal, persistent project threads and conversations, combined with a continuously updating view of agent activity and workspace media. A person can see work as it happens, send guidance while it matters, inspect generated artifacts, and control running work. The user can use it for an ordinary text-only coding conversation without touching the gallery.

## Core workflows

1. Connect a T3 environment, choose or create a project and workspace, create a named thread, choose an available provider and model, and send a message. Read the response, tool calls, errors and approvals inline; send follow-ups into the same thread and revisit history after restart.
2. Navigate multiple threads and concurrent runs, see actual status and pending requests, keep separate drafts, find earlier messages, and switch without losing place. Display true workspace, branch and provider identity. Thread management and controls must reflect discovered T3 capabilities.
3. Watch assistant text and tool activity as available. See newly created or changed images, 3D, video, audio and code in an Inspector/Live Gallery-style feed, open details and compare captured revisions. Attribute workspace observations honestly; never infer agent authorship solely from timing.
4. Send guidance with an explicit destination and delivery state. Distinguish queued messages, supported in-flight steering, questions and permission decisions. Show what T3 actually acknowledged.
5. Stop work with a normal interrupt or explicit force option where the real integration and process ownership allow it. Offer backgrounding of eligible work only when its actual lifecycle can be preserved and observed. Never label a killed CLI waiter as a stopped server-side run or promise that arbitrary provider-owned work can be detached. Explain unavailable operations in context.
6. Surface provider-native and T3 child activity with real lineage where available, plus pending questions and settlement; do not fabricate external access to parent-only delegation.

## Architecture decision and risks

T3 remains authoritative for its threads, providers, permissions and state; a Rust service owns the UI-facing read model, gallery and local observations. Start with the documented CLI/MCP control path and evaluate a separately authenticated, pinned T3 client-runtime bridge for live RPC events. This is a proposed compatibility adapter, not a stable streaming API guarantee. CLI polling alone cannot guarantee token-level streaming. If live RPC or interruption is unavailable, show the precise limitation; investigate an upstream extension or maintained fork before claiming full coverage. Keep credentials separate and never write T3's database. See [integration details](02-t3-integration.md).

## Delivery milestones and gates

Council direction: prioritize one complete conversation-to-output-to-feedback journey. The first usable slice includes ordinary stop, pending decisions and a basic changes view; advanced force, detached execution, broad codecs and rich timeline features follow proof of the real T3 integration. Thread selection is independent of the selected view. Keep review artifacts in explicit watched folders, offer a suggested output folder and disclose unwatched locations; never imply machine-wide temporary-file discovery.

Quality-of-life priorities from the final council review: show an editable local message queue and its real delivery state; surface pending questions and approvals at the thread and conversation level; provide a checkout-scoped read-only diff and links to actual test output; make thread history searchable and resumable with honest completeness; and expose provider, model and context information only when available. Claude Code documents [queued messages](https://code.claude.com/docs/en/interactive-mode#queue-messages-while-claude-works); VS Code documents [reviewing edits and diff feedback](https://code.visualstudio.com/docs/agents/run/review-code-edits). These are design precedents, not evidence that T3 exposes identical capabilities. Defer universal rewind, embedded terminal and broad background-process control until their actual scope is proven.

1. **Contract spike:** run an isolated T3 environment and capture sanitized evidence of authentication, thread creation, follow-up, actual live events, approvals, interruption and reconnection. Verify the installed version and bridge packaging. Establish which background and force operations are genuinely available per provider. Gate: observed behavior and documented gaps, with no claims based solely on source.
2. **Normal coding harness:** project/thread navigation, create/open thread, provider/model selection, composer, conversation history, streaming where verified, tool results, pending requests, ordinary stop where supported, and a basic checkout-scoped diff. Gate: create a thread, conduct multiple turns, switch threads, restart and restore history, answer an actual request, and handle failure/reconnect without duplicated messages.
3. **Live workspace:** integrate Rust event reducer and gallery watcher; add activity and artifact views, filters, selection, pause/catch-up and image/3D inspection. Gate: render and interact with real fixtures, burst updates and corrupt files; preserve selection and disclose gaps.
4. **Steering and execution controls:** supported in-flight guidance, normal stop, force stop and eligible background operations, each with explicit state and scope. Gate: provider-specific end-to-end tests for completion races, child processes, queued sends, pending approvals and restart recovery. Disable unsupported operations.
5. **Rich media and history:** video/audio/code, revision capture and comparison, accessible controls and retention settings. Gate: actual playback, code diff and visual inspection of images and models, plus resource limits and privacy/deletion tests.
6. **Harden and release:** capability/version matrix, packaging, diagnostics, security, performance, migration, cross-platform and remote environment tests. Gate: documented supported versions and real-provider smoke tests; unknowns stay visible.

## Measurable acceptance

- Conversation messages and tool states match the authoritative thread through navigation, reconnect and restart; queued, running, completed and interrupted are distinct.
- In a controlled streaming fixture, capture timestamps at provider/T3 observation, Rust ingestion and UI render; report latency distributions and losses against a baseline. Never imply unseen provider output was delivered.
- A slow client, disconnect, oversized output or expired replay window yields an explicit gap or resnapshot, not silent loss or a stuck feed.
- A force action reports exactly which owned process or provider operation was targeted and its observed result. Background work remains findable with output and terminal status when the provider supports it.
- Artifact previews and revision comparisons are checked visually with real fixtures; successful indexing alone is not visual acceptance.

## First decisions to validate

Verify the active T3 build and supported provider operations; determine whether an independently authorized RPC bridge can be packaged and maintained; define which executions can actually be backgrounded or force-stopped; and choose a retention default after measuring artifact and event volume. These are implementation spikes, not prerequisites for designing ordinary thread and conversation UX.
