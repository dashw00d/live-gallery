# Rust port: how the work is split

The Python script `live-gallery` is the reference: the Rust binary must behave the same (same CLI flags,
same HTTP routes and JSON, same SSE events, same state.json / thumbnail cache locations). The page,
`kit.js` and `worker.js` were extracted verbatim into `assets/` and are embedded with `include_str!`.
Do not edit `assets/`.

| Module | Owner | Python counterpart |
|---|---|---|
| `src/item.rs` (kind_of, make_item bodies), `src/watcher.rs` | watcher agent | `kind_of`, `Inotify`, `Watcher` |
| `src/app.rs`, `src/util.rs`, `src/main.rs` | app agent | `App`, `norm_roots`, `complete_dirs`, thumb helpers, `main` |
| `src/server.rs` | server agent | `make_handler` |
| `src/events.rs`, type definitions in `src/item.rs`, `Cargo.toml` | integrator | |

Rules
- Keep the public signatures in the skeleton. If you truly need a change to a shared type or another
  module's signature, note it in the "Requests" section below instead of editing someone else's file.
- Only edit files you own. Adding a dependency: note it under Requests (integrator adds it).
- Unit tests go in your own module (`#[cfg(test)] mod tests`). `cargo test` must pass for your module.
- Don't commit; the integrator commits.

## Requests
