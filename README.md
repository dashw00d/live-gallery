# Live Gallery

**Watch a folder and see every new image or 3D model the moment it appears, however deep it's nested.**

Made for following AI agents (or build scripts, renderers, exporters…) that scatter their output across
subfolders. Instead of digging through `run3/renders/lane_c/…`, keep one browser tab open: new files
slide in at the top, newest first.

- One file, Python standard library only, nothing to install.
- Images: png, jpg, gif, webp, svg, avif, bmp, ico
- 3D: glb, gltf, obj, stl, ply, fbx. You get rendered thumbnails plus an orbit viewer (three.js, loaded from a CDN).

## Run it

Needs Python 3.8+.

```bash
python3 live-gallery ~/path/to/folder --open      # macOS / Linux
py live-gallery C:\path\to\folder --open          # Windows
```

Then open http://localhost:8765 (`--open` does it for you). You can change the folder from the page too.

## What you get

- **Live grid.** New files get a green **NEW** badge. Re-saved files jump back to the top marked **UPDATED**,
  and deleted files disappear. Files show up once they've finished writing, never half-saved.
- **Several folders at once.** Each watched folder is a chip at the top. Click a chip to show only that
  folder, or click × to stop watching it. Use the **Add a folder…** box to add more: it autocompletes paths
  and suggests recent folders. Every card shows which folder it came from. Folders already inside a watched
  folder are skipped. You can also pass several on the command line (`live-gallery ~/a ~/b`) or bookmark
  `?watch=/path/one,/path/two`.
- **Filters.** All / Images / 3D. Filter by path (press `/`). Click a card's folder to show only that folder.
- **Follow.** Each new file opens full-size as it arrives, so you can just watch.
- **Pause.** Holds new arrivals so the grid stops moving while you look.
- **Viewer.** Click an image to see it at 100%, scroll to zoom up to 16×, drag to pan (`1` = 100%, `0` = fit).
  3D models: drag to orbit, scroll to zoom. Use ←/→ for the next/previous file. Click the backdrop or press Esc
  to close. "Watch this folder" and "Copy path" buttons are in the bar.

## Options

```
live-gallery [DIR ...] [--port N] [--default DIR] [-x NAME] [--poll] [-i SECS] [-n N] [--host H] [--open]
```

| Flag | Meaning |
|---|---|
| `DIR ...` | Folders to watch. Without it you get the last folder you picked in the page, else `--default`, else the current folder. |
| `-x NAME` | Skip folders with this name (repeatable). `.git`, `node_modules`, venvs, caches, `vendor`, `target`, `.godot`, `.import` and similar are already skipped. |
| `--poll`, `-i SECS` | Check for changes every SECS seconds (default 1) instead of using inotify. |
| `-n N` | How many existing files to show at start (default 150, newest first). |
| `--port N` | Port (default 8765, or the next free one). |

## How it watches

- **Linux.** Uses inotify, so it's idle until something changes and files appear instantly. Each folder takes one
  inotify watch. A tree with ~100k folders is fine under the usual limit; raise `fs.inotify.max_user_watches`
  if you watch something enormous.
- **macOS / Windows.** Checks the folders every second instead. That's great for a project folder. For very
  large trees use `-i 3` or `-x` to skip big folders.
- **WSL.** Run it inside WSL and open `localhost:8765` in your Windows browser. Use `--poll` for folders under
  `/mnt/c`, because changes made from Windows don't trigger inotify there.

## Notes

- Only serves image/3D files from inside the folders you're watching, and only listens on `127.0.0.1` by default.
- Your chosen folder and recent folders are saved in `~/.config/live-gallery/state.json`.
- 3D previews need internet the first time (three.js comes from jsDelivr). Images work offline.
