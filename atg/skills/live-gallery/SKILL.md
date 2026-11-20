---
name: live-gallery
description: >-
  Open and interact with the Live Gallery side panel in Antigravity 2.0, which
  streams agent-created 3D models, images, videos, audio, text, and code in
  real time. Use when the user asks to open Live Gallery, view generated media
  or outputs live, or add a folder to the live stream.
---

# Live Gallery Side Panel

The `live-gallery` plugin runs a sidecar-backed web panel in Antigravity 2.0's
Auxiliary (Side) Pane that streams workspace files, artifacts, and agent
outputs (3D models, images, videos, audio, code, text, and agent replies) in
real time.

## Opening the panel

If the sidecar is enabled and running, offer the user a clickable pill so they
can toggle the panel immediately:

```markdown
[Live Gallery](sidecar://live-gallery/live-gallery/)
```

Before emitting the pill, confirm the sidecar is enabled/running (you can check
whether `~/.cache/live-gallery/sidecar-runtime.json` exists and its port
responds to `GET /healthz`). If it isn't running yet, point the user to
[Live Gallery](customization://live-gallery) so they can enable the plugin and
its sidecar.

## Adding folders programmatically

When the sidecar is running on the port recorded in
`~/.cache/live-gallery/sidecar-runtime.json`, you can add an extra watched
folder via `POST http://127.0.0.1:<port>/api/watch` with JSON body
`{"add": "/abs/path/to/folder"}` (or replace roots with `{"roots": [...]}`).
Active workspaces and artifact directories are registered automatically via
hooks.
