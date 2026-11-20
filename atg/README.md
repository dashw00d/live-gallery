# Live Gallery — Antigravity 2.0 Plugin

A sidecar-backed UI plugin that embeds a real-time multimodal output stream inside Antigravity 2.0's Auxiliary (Side) Pane.

## What it streams
- **3D models** (`glb`, `gltf`, `obj`, `stl`, `ply`, `fbx`) with cached WebWorker thumbnails and an interactive Three.js orbit viewer
- **Images** (`png`, `jpg`, `webp`, `gif`, `svg`, `avif`, `bmp`, `ico`) with zoom/pan lightbox
- **Videos** (`mp4`, `webm`, `mov`, `m4v`, `ogv`) and **Audio** (`mp3`, `wav`, `ogg`, `flac`, `m4a`, `aac`) with HTTP Range seeking
- **Code & Text/Docs** (syntax files, Markdown, CSV, logs, PDFs) with live snippet cards and full viewer
- **Agent Outputs & Artifacts** tailed directly from `~/.gemini/antigravity/brain/` (`transcript.jsonl` + conversation artifact folders)
- **Auto-follow written folders** — automatically detects any folder an agent writes to (via `write_file`/`edit_file`, `run_command` output flags/redirects, MCP tools, media attachments, or `transcript.jsonl`) and follows it live via `inotify`. Dismissed folders (`×`) are remembered so they aren't re-added; toggle **Auto-watch** in the header at any time.
- **Two-way steering** via `agentapi send-message` / `window.sidecar.agent.sendMessage` right from any card

## Install / Reinstall

```bash
agy plugin validate --strict ./atg
agy plugin install ./atg
```

You can also run the server standalone outside Antigravity:

```bash
python3 ./atg/sidecars/live-gallery/server.py ~/path/to/workspace
```
