# Live Gallery and Inspector — feature inventory

This is a feature inventory of two related apps: Ryan's **Live Gallery** and his friend's **Inspector**. It is for understanding what each app does, so something similar can be built later. It is not a repair plan, a bug-fix list, or a design for a future app.

**Status tags** used on every feature:

| Tag | Meaning |
|---|---|
| **Tested ✅** | Exercised in the running app (Inspector: clicked or observed in the GUI; Live Gallery: confirmed with a read-only HTTP GET against the running server, or an equivalent direct check). |
| **Tested, failed ❌** | Exercised, and the observed result did not do what the control or label suggests. A failure on the box may be the app, the environment, or both; box caveats are called out rather than treated as a verdict on the product. |
| **Inferred (code or binary strings)** | Taken from Live Gallery source, from strings in the Inspector binary, or from a settings file. Not confirmed in the running UI. |
| **Not verified** | Mentioned or hinted at, but not successfully exercised. |

Sources, all under `/workspace/inspector-study/`:

- `live-gallery-features.md` — Live Gallery inventory. Items there are marked verified against the running app (**[V]**) or read in code (**[C]** / **[V-asset]**).
- `inspector-static.md` — static clues from the Inspector binary. Unverified unless a later GUI pass confirmed them.
- `inspector-inventory.md` — GUI part 1, tested.
- `inspector-inventory-part2.md` — GUI part 2, tested (live updates, History/Compare, burst, multi-select, 3D and image formats, crash isolation, Ctrl+O / Add project).
- `live-gallery/` source, `run.log`, `settings.default-empty.json`, `settings.after-cli-arg.json`.
- Screenshots in `screenshots/` (including `p2-*`). Paths below are relative to this directory.

---

## 1. Overview

### 1.1 What each app is

**Live Gallery** is a local web app that watches one or more folders recursively and shows every image and 3D model in a live grid, newest first. It is aimed at following AI agents, build scripts, and renderers that scatter output across deep subfolders. The running implementation is a Rust port (`axum` + `tokio`, Linux `inotify`) that serves a web UI (`assets/index.html`, `kit.js`, `worker.js`). The 3D viewer uses **three.js r160** (loaders plus Draco and Meshopt; scripts come from the jsDelivr CDN, Draco from gstatic). State lives in `~/.config/live-gallery/state.json`. 3D thumbnails are cached in `~/.cache/live-gallery/thumbs/`. A Python stdlib reference script (`./live-gallery`) shares the same flags, page, state file, and thumbnail cache. Ryan's running copy is the Rust binary, started as `target/release/live-gallery --default /home/ryan/.t3/worktrees --host 127.0.0.1 --port 29024`, and it matched the source assets exactly (md5 of `/`, `/kit.js`, and `/worker.js`).

**Inspector** is a native Linux desktop app written in Rust on Zed's **GPUI 0.2.2**, with the blade/**Vulkan** renderer and cosmic-text for text. The window class / app id is `inspector-app`. The UI font is Geist / Geist Mono. The binary identifies itself as **0.1.0** and includes third-party notices that say "Inspector is proprietary software." Settings live at `~/.config/Inspector/settings.json`. It watches project folders, shows a Feed of images, 3D, video, audio, and code, and adds an Inspector panel (Details / History / Compare), a live activity timeline, a Git/language/storage Overview, and sharing/export actions. Media playback goes through **ffmpeg** / **ffplay** / **ffprobe** (inferred from binary strings; playback itself was tested). Overview git stats shell out to `git`. Code highlighting is inferred to use syntect + two-face.

### 1.2 How this was tested

- A copy of the Inspector binary (`/workspace/inspector-study/inspector`, 32.3 MB) was run on the box, watching a 64-file sample git repo at `/workspace/inspector-study/samples` (built by `make_samples.py`). Passing that folder as `./inspector <dir>` added it as a saved project (**Tested ✅**).
- GUI part 1 clicked through layout, Feed, previews, the Inspector panel, Overview, Settings, and shortcuts. GUI part 2 ran `live_changes.sh` (modes add / modify / model / code, then a 10-file burst and a deletion) from **18:07:52 to 18:14:13 CST (America/Chicago)** on Sun Nov 15, 2026, and probed History/Compare, 3D and image formats, multi-select, and Add project.
- Live Gallery was not clicked in a browser in these passes. Its inventory comes from a full read of `live-gallery/src/*.rs` and the web assets, plus read-only HTTP GETs against Ryan's running instance at `http://127.0.0.1:29024/` (36,905 files: 35,102 images and 1,803 models, three roots, `mode = "inotify, 175285 folders"`). Served UI assets were byte-identical to the source, but UI widgets were not clicked. In this document, Live Gallery HTTP-confirmed behavior is **Tested ✅**; UI behavior known only from that matching source is **Inferred (code or binary strings)**.

### 1.3 Box-environment caveats

These limits on the box may explain some Inspector failures, and they are not a verdict on how the app behaves on a typical desktop:

- **No GPU.** The app ran on Mesa **lavapipe** (software Vulkan). Without a Vulkan ICD it panics with `NoSupportedDeviceFound` (**Tested ✅** in earlier launch attempts). 3D zoom/pan that was not visually confirmed could also be a software-renderer limitation.
- **No folder-picker backend.** No zenity, kdialog, or xdg-desktop-portal. Ctrl+O and **Add project…** did nothing visible.
- **No clipboard helper.** No xclip or wl-copy. Some copy actions still toasted success (`Copy image`, `Copy frame`); `Copy PDF` and `Save review clip` returned `No such file or directory (os error 2)`.
- **`xdg-open` is installed, but Chrome handles it.** Open file / Reveal in folder opened Chrome at a local directory index (and in one case downloaded the file) instead of a native editor or file manager.
- **ffmpeg, ffplay, and ffprobe are installed**, so missing-FFmpeg messages were not triggered.
- Modifier clicks and Ctrl+A were sent through **xdotool**. If Inspector reads modifiers differently than that path delivers them, multi-select may exist but was not triggered here.

---

## 2. Inspector by area

### 2.1 Launch, CLI, and projects

**Launch.** Starting the binary opens a native window. First launch with no project shows sidebar `Open a project ▾`, Feed / Overview, an empty FOLDERS section, type tabs, a grid icon, `Last modified ▾`, a right-hand Inspector panel ("Select a file to inspect."), and a `Live activity` strip (`Last hour ▾`, green dot). Status bar: `0 projects · 0 files · ● Ready`. Observed window size was 1500×940 on a 1920×1200 display. **Tested ✅** (first-run screenshots, then the samples session).

**CLI flags.** `./inspector --help` and `-h` print nothing and just open the GUI. No clap/argv usage text was found in the binary. **Tested ✅**

**Positional folder argument.** `./inspector /path/to/dir` adds that folder as a project: it is written into `settings.json` `roots`. A second path argument is ignored. **Tested ✅** (`settings.after-cli-arg.json` has `roots: ["/workspace/inspector-study/samples"]`; the default-empty snapshot has `roots: []`).

**Headless report export.** Binary strings include `Expected project path`, `Expected output PNG or PDF path`, and `Project folder does not exist`. Running `./inspector <dir> /tmp/ov.png` or `.pdf` did **not** write a report; it just opened the GUI. **Inferred (code or binary strings)** for the mode itself; the two-argument attempt is **Tested, failed ❌** (no report file written; the invocation may simply have been the wrong shape).

**Multiple instances.** Several instances can run at once; no single-instance lock was observed. Each one rewrites `settings.json`. **Tested ✅** (static-analysis launches)

**Project selector.** With a project loaded, the top/sidebar control shows the project name (`samples`) and, when an icon is found, an auto-detected project icon (`assets/icon.png` in the sample repo). The menu lists the active project with a check (`samples ✓`) and **Add project…**. **Tested ✅** (`screenshots/p2-project-menu-add-project.webp`)

**Add project.** Clicking **Add project…** closes the menu; no picker and no error toast appear. Ctrl+O likewise does nothing visible, and no zenity/kdialog/portal process starts. The app stays responsive. **Tested, failed ❌** — silent on this machine, consistent with no folder-picker backend (see §1.3). Screenshots: `screenshots/p2-after-ctrl-o-nothing.webp`, `screenshots/p2-after-add-project-click-nothing.webp`.

**Drop a folder.** The empty state reads `Open a project — Drop a folder anywhere to start watching.` Drag-and-drop was not tried. **Not verified** (string is **Inferred** plus a first-run screenshot; the gesture was not tested).

**Remove project.** The project menu and binary strings mention it. It was not clicked, to avoid changing the saved project. **Not verified**

**Switch project.** Binary strings mention `switch-project` / `Add projects`. Only one project was loaded. **Not verified**

**Persistence.** `~/.config/Inspector/settings.json` is created on first launch (`schema_version` 2). The samples path remains in `roots` across restarts. During the GUI session the file also accumulated `folder_overrides` (images and media set `true`) and `project_seconds` (review-time accumulator for the project). **Tested ✅**

### 2.2 Top bar and search

**Layout.** Inspector logo/name at left; project selector; a centered `Search files…` field labeled `Ctrl K`; standard window controls at right. **Tested ✅**

**Search.** Ctrl+K focuses the field. Typing a name (e.g. `clip.mp4`) filters the Feed to matching files; clearing the field restores the full feed. No separate advanced-filter control was seen. **Tested ✅**

Matching is by filename/path substring in practice (the `clip.mp4` and later `mislabeled` searches). The exact match rules (case, path vs name only) were not spelled out beyond that. Binary placeholder text is `Search files...`.

**Empty filter.** Binary string: `No matching files — Try a different folder, file type, or search.` **Inferred (code or binary strings)** (not deliberately triggered in the GUI notes).

### 2.3 Sidebar (Feed / Overview / folders)

**Nav.** `Feed` and `Overview` switch the main pane. A settings gear / Ctrl+, opens Settings. **Tested ✅**

**FOLDERS.** A tree with **All folders** and one checkbox row per top-level folder, with a file count. In the initial samples project the visible rows included `.hidden_dir (1)`, `assets (1)`, `code (6)`, `ignored_by_gitignore`, `images (23)`, `media (8)`, `models (16)`, `nested (3)`, and `watch_me (1)`. `.git`, `build`, and `node_modules` appeared **unchecked and greyed**, matching the default `excludes` list. Hidden folders other than those excludes **are** included. `ignored_by_gitignore` was **checked**, which lines up with **Include ignored media** being On (`media_bypass_ignore: true`) — `secret.png` is under a gitignored directory and still appeared. **Tested ✅** (presence and default check state). Folder include checkboxes were not broadly toggled, so turning a folder off was **Not verified**.

**Folder counts update live.** After the change script, `watch_me` went from 1 → 17 and the status-bar file count from 61 → 77 (then 78 before a deletion dropped it to 77). **Tested ✅**

**Rescan folder.** Right-click a sidebar folder → **Rescan folder**. Clicked on `images`; it returned to the normal view with no visible error and no destructive effect. **Tested ✅** (the rescan itself; what it rebuilds was not independently audited).

**Recursive watch.** Nested files such as `nested/level1/level2/level3/deep_2.png` and `models/nested/sub/bracket.stl` appeared with Watch subfolders On. **Tested ✅**

### 2.4 Feed

**Header and tabs.** The header shows `Feed N`. Tabs: **All files / Images / 3D / Video / Audio / Code**. Initial All-files count was 61. Observed filtered counts: 3D **11**, Video **4**, Audio **4**. Images and Code tabs are present; opening the Code tab crashed the app (see §6) because `images/mislabeled.jpg.txt` is treated as code. Individual code files opened from All files are fine. **Tested ✅** (tab presence and counts); Code tab **Tested, failed ❌**.

The 3D tab's 11 items are the models folder minus the four `.bin` buffers and `cube.3mf` (3MF was not listed there). `sphere.ply` is listed but does not preview (see §3). Video 4 and Audio 4 match the four video and four audio sample files, so those extensions are at least **indexed**.

**Cards (grid).** Thumbnails or previews where available, plus filename, dimensions/size, type, and age. Some formats show a generic **File** placeholder; some 3D files show **Preview unavailable**. **Tested ✅** (`screenshots/p2-images-tab-grid.webp`, `screenshots/p2-live-feed-updated-badges.webp`)

**List view.** Toggle **Switch to list view** / **Switch to grid view**. List rows show a timestamp, `Modified` (or Added / Removed), a relative path, and a type icon. **Tested ✅** (`screenshots/list-view.webp`, `screenshots/p2-list-removed-deleted-and-burst-rows.webp`)

**Sort.** The visible control is `Last modified`, toggling **Newest first** / **Oldest first**. Clicking it reversed the order; it was restored to Newest first. No other sort keys were exposed. Binary strings also mention `Recent / Oldest`, which may be the same pair. **Tested ✅** for the two observed options.

**Badges.** New or changed cards get a green **Updated now** badge and are re-sorted to the top. List-view event colors: **Added** = blue dot, **Updated/Modified** = green, **Removed** = red dot. **Tested ✅**

**New changes pill.** When the feed is scrolled down and changes arrive, a **New changes ↑** pill appears at the top-right of the feed (`screenshots/p2-new-changes-pill-before-now-slider.webp`). Clicking it jumped to the top, but the selection also changed to the card under the pill (`openexr.exr`) after the layout shifted (`screenshots/p2-after-pill-click-exr-selected.webp`). So the click may fall through onto a card. **Tested ✅** (pill appears and scrolls); the targeting side-effect is an observation in §6.

**File-cap warning.** Binary string: `Showing the first N files. Increase the file limit in Settings, or watch a narrower folder.` Default `file_limit` is 50,000; the sample set is far smaller, so this was **Not verified**.

**Feed count vs file count.** After live edits, `Feed N` could show change events (e.g. 65) while the status bar showed a different file count (e.g. 63). **Tested ✅**

**Empty project copy.** `Open a project — Drop a folder anywhere to start watching.` **Tested ✅** (first-run empty state)

### 2.5 Inspector panel (Details / History / Compare, Open / Reveal)

Selecting a file opens the right-hand **Inspector** panel (close `×`). Binary strings also mention hide/show inspector. Default width in settings is `inspector_width` 340. **Tested ✅** (open/close and contents). Default newest-file auto-select on project load: **Tested ✅**.

**Details.** Shows type (e.g. `Type Image`), size, modified time, and relevant dimensions or preview info (images: `Dimensions 128 × 128` for `assets/icon.png`; 3D: triangle counts). A prompt **Open this file in its default application** appears for some generic-file types. **Tested ✅**

**History.** Tab label **History**, heading **Captured revisions**. Entries are **Current**, **Revision 2**, **Revision 1**, … with thumbnails, timestamps, and size/dimensions (`screenshots/p2-code-history-tab.webp`). The cap is **3** (`settings.json` `"versions": 3`); older revisions fall off. History is **not** kept across app restarts — after the crash/restart, version history reset to Current only. A live-edited model (`watch_me/model_change.stl`) accumulated 3 revisions during the script. **Tested ✅**

There is a Settings **Preview history → Clear** button; it was not clicked. **Not verified**

**Compare.** Heading **Version history** (Current, Previous · 1, Previous · 2, …) plus **Recent activity**.

- **Images:** a **Before / Now** slider with a draggable divider handle (`screenshots/p2-new-changes-pill-before-now-slider.webp`). The control was present on `will_change.png`. The divider was not dragged, and that sample is rewritten to red every round, so both sides looked red. Slider UI: **Tested ✅**; dragging it: **Not verified**.
- **Code:** an inline unified diff with two line-number columns (old/new); added lines are green with a `+` marker; unchanged lines are plain (`screenshots/p2-code-diff-compare.webp`). Choosing **Previous · 2** diffs that version against Current. No side-by-side mode was seen. The panel is narrow and long lines are clipped. **Tested ✅**
- **3D:** with only a current revision, no Before/Now content diff was visible for `bracket.stl` in part 1. Multi-revision model compare was **Not verified** as a visual diff (History did list 3 revisions for `model_change.stl`).

Binary strings mention the `similar` crate / `compare_contents`. **Inferred (code or binary strings)** as the engine; the UI above is tested.

**Open file.** Present in the panel and the context menu. Clicking it for `bracket.stl` switched to Chrome, which showed a local directory index and a completed `bracket.stl` download, rather than a 3D editor. The Inspector window remained available in the taskbar (unless it had crashed). **Tested ✅** as an action that runs; the handler on this desktop is Chrome via `xdg-open` (see §1.3).

**Reveal in folder.** Present at the bottom of the panel and in the context menu. Clicked for the same model, it opened Chrome at a local directory index of the containing folder, with `bracket.stl` listed — not a native file-manager window. **Tested ✅** with the same desktop-handler caveat.

**Selection during live updates.** A selected file stays selected while other changes arrive, and the panel keeps showing it. When the selected file itself changes, the panel gets a new revision. Layout shifts under the cursor as new cards are inserted at the top (easy to mis-click). **Tested ✅**

### 2.6 Live watching and the timeline

**Automatic updates.** New and changed files appear in the Feed with no manual refresh. Example: `new_180752.png` was written at 18:07:52.7 CST; `model_change.stl` (18:07:57) showed as a list row "Added 18:07:57" within a few seconds. Cards re-sort newest-first and pick up **Updated now** badges; folder and file counts update. **Tested ✅** (`screenshots/p2-live-feed-updated-badges.webp`, `screenshots/p2-3d-list-live-added-model-change.webp`)

**Pause.** A pause button on the activity strip toggles **Live activity** ↔ **Paused activity**, and the status bar **Watching** ↔ **Paused**. While paused, a new file (`new_181139.png`) was **not** added to the feed (count stayed 66), but the already-visible `live_edit.rs` card text did refresh, and **Updated now** badges dropped. On resume the feed caught up immediately (67, new card present). **Tested ✅** (`screenshots/p2-paused-activity.webp`, `screenshots/p2-paused-new-file-not-shown.webp`, `screenshots/p2-resumed-catchup.webp`)

**Range menu.** **Last 5 minutes / Last 15 minutes / Last hour / Last 24 hours**. `Last hour` is the initial/default. Changing the range changes the time axis. **Tested ✅**

**Tick filtering.** Clicking a timeline tick filters the Feed to a time-range chip (e.g. `18:09:52–18:10:19 ×`). A **Back to latest** button then appears at the bottom right of the strip; clicking it restores the full feed (`screenshots/p2-timeline-range-back-to-latest.webp`, `screenshots/p2-after-back-to-latest.webp`). Mouse-wheel over the timeline does nothing. **Tested ✅** (click-to-filter and Back to latest); wheel-to-pan/zoom the timeline: no effect observed.

**Removals.** After the script deleted `watch_me/new_180752.png`, list view showed a row `18:14:13 Removed watch_me/new_180752.png` with a red dot, and the file count dropped 78 → 77. **Tested ✅** (`screenshots/p2-list-removed-deleted-and-burst-rows.webp`)

**Burst.** Ten simultaneous `burst_181333_N.png` files appeared as ten separate Added entries / ten separate cards, all with **Updated now** badges (two large cards, then a 3-wide grid). No collage, stack, or group header. The timeline just shows several ticks. **Tested ✅** (`screenshots/p2-burst-10-cards.webp`)

**Follow new files.** Settings → Activity, default **Off** (`follow_latest: false`). Auto-select/follow behavior was not turned on and tested. **Not verified**

**Debounce / batching.** Settings **Update batching** 250 ms (`debounce_ms`). The 10-file burst still landed as 10 cards. Finer timing of the debounce was **Not verified**.

**Status bar states.** Observed: `Ready`, `Watching`, `Paused`, plus `1 project · N files`. Binary strings also include `Scanning`, `Reading files`, `Reading project`, `Updated.`, `File watcher unavailable.`, `Folder limit reached (32).`, `Project scan timed out`, `Could not watch …`. Those others were **Not verified**.

**Activity history size.** Settings default 2048 events (`events`). Not stressed. **Not verified** beyond the control existing.

### 2.7 3D viewer

The Inspector panel (and cards, when a thumbnail can be built) render models in a built-in viewer. A **Reset view** button sits below every viewer, including failure states. **Tested ✅** (presence). Part 1 clicked Reset view on `bracket.stl` after a small rotation; part 2 did not re-confirm that it fully restores an orbit. Treat restore-after-orbit as only weakly observed.

**Controls.**

- **Left-drag rotates.** Confirmed on `scene.gltf` (orientation changed). **Tested ✅** (`screenshots/p2-3d-rotate-scene-gltf.webp`)
- **Scroll zoom.** Wheel up/down (5–15 clicks) on cube, torus, and `scene.gltf` produced no visible size change. **Not verified** (no zoom observed; lavapipe may be a factor).
- **Right-drag pan.** Not observed. **Not verified**
- No other view buttons were seen.

**Stated coverage** (on-screen error text, also in the binary): **GLB, glTF, OBJ, and binary STL**. ASCII STL is rejected. Embedded or remote (data-URI) buffers are not supported. External glTF buffers must stay inside the model's folder (**Inferred** for the "inside the folder" rule; a same-folder `.gltf` + `.bin` scene **did** render). Model cap 64 MB and messages such as `Invalid model coordinates` are **Inferred (code or binary strings)**.

**Samples in the panel / cards:**

| File | Result | Status |
|---|---|---|
| `cube_binary.stl` | Renders (12 triangles) | **Tested ✅** (`screenshots/p2-3d-binary-stl.webp`) |
| `cube_ascii.stl` | Panel: `Only binary STL is supported` | **Tested, failed ❌** as a mesh preview (`screenshots/p2-3d-ascii-stl-unsupported.webp`) |
| `big_sphere_330k_tris.stl` | Card thumbnail showed the sphere; not separately opened in the panel | **Tested ✅** (card) |
| `models/nested/sub/bracket.stl` | Renders in the card (tall bar); earlier panel open reported 12 triangles and allowed a slight rotate | **Tested ✅** (`screenshots/model-viewer.webp`) |
| `torus.obj` | Renders (2048 triangles) | **Tested ✅** (`screenshots/p2-3d-obj-torus.webp`) |
| `empty.obj` | `Model has no supported triangles` | **Tested, failed ❌** as a mesh (`screenshots/p2-3d-empty-obj.webp`) |
| `sphere_colored.glb` | Renders (1280 triangles) but **grey** — vertex colour not applied | **Tested ✅** (mesh); colour **Tested, failed ❌** (`screenshots/p2-3d-glb.webp`) |
| `scene_separate/scene.gltf` + `.bin` | Renders (140 triangles, cylinder + cube) | **Tested ✅** (`screenshots/p2-3d-gltf-separate-bin.webp`) |
| `embedded_datauri.gltf` | `Embedded or remote buffers are not supported` | **Tested, failed ❌** as a preview (`screenshots/p2-3d-embedded-gltf.webp`) |
| `sphere.ply` | `Preview supports GLB, glTF, OBJ and binary STL.` | **Tested, failed ❌** (`screenshots/p2-3d-ply.webp`) |
| `cube.3mf` | Not listed in the 3D tab (11 items at start); not opened individually | **Not verified** (appears not treated as a 3D type) |
| `broken.glb` | `failed to fill whole buffer` / Preview unavailable | **Tested, failed ❌** (`screenshots/p2-3d-broken-glb.webp`) |
| `watch_me/model_change.stl` | Renders (cylinder, 128 triangles) and updates each live round (3 History revisions) | **Tested ✅** |

PLY, FBX, and 3MF are not in the supported-preview set (FBX was not in the sample tree). **Inferred** from strings and from the PLY error; FBX itself is **Not verified** in the GUI.

### 2.8 Image, video, audio, and code previews

#### Images

Opened from the Images tab grid and the Inspector panel.

**Render as an image** (**Tested ✅**, `screenshots/p2-images-tab-grid.webp`): PNG (`gradient`, `alpha_transparent`, `tall_strip`, `wide_banner`, `tiny_1x1`), JPEG (`photo`, `tiny_8x8`, `large_6000x4000.jpg` — 567 KB, still previews), WebP (`pic`, `animated`), GIF (`still`, `animated`), TIFF (`scan.tiff`), BMP (`legacy.bmp`). Unicode filename `ünïcødé name (copy).png` renders with the correct name (**Tested ✅**, `screenshots/p2-img-unicode-name-ok.webp`).

**Animated GIF / WebP.** Cards and panel stayed on **frame 0** for minutes; they do not animate. **Tested, failed ❌** (`screenshots/p2-img-animated-gif-static-frame0.webp`). Binary strings mention animated GIF/WebP codecs, but animation was not observed.

**Generic "File" card**, panel: `Open this file in its default application.` — **EXR, HDR, TGA, ICO, PPM**. **Tested ✅** as a generic-file fallback (`screenshots/p2-img-tga-generic-file.webp`, `screenshots/p2-img-ppm-generic-file.webp`, `screenshots/p2-img-ico-generic-file.webp`). The binary's compiled image-crate list includes ICO, TGA, PNM, HDR, OpenEXR and others, but these samples were not previewed as images.

**SVG.** Shown as syntax-coloured **source text**, type **Text**, not rendered as a graphic. **Tested ✅** (`screenshots/p2-img-svg-as-source-text.webp`). Binary strings mention resvg/usvg; that path was not what the UI did here.

**corrupt.png.** Card: `Preview unavailable`. Panel error: `Format error decoding Png: ChunkType { type: <control chars>, critical: false, private: true, reserved: true, safecopy: true } chunk appeared before IHDR chunk`. No crash. **Tested ✅** (`screenshots/p2-img-corrupt-png-error.webp`)

**mislabeled.jpg.txt** (a PNG whose name ends in `.txt`). Treated as code/text. Rendering its card **crashes** the app (cosmic-text panic). **Tested, failed ❌** — see §6.

**Image zoom / pan.** Wheel on the panel preview does nothing; no zoom controls were visible. Binary strings mention an expanded preview (`Zoom in`, `Zoom out`, `Fit`, `preview-native` / 100%, `close-preview`). That expanded viewer was **Not verified**. In-panel zoom: no effect observed.

#### Video

The Video tab listed all four sample videos (`clip.mp4`, `.mkv`, `.mov`, `.webm`). **Tested ✅** (indexing / tab count). Card frame previews were seen for mp4 (clicked) and, on first load, mov/mkv.

**Player (clip.mp4).** Timeline, play/pause, time (`0:00 / 0:04`), **Copy frame**, volume (`80%`). Play advanced to about `0:03 / 0:04` and the preview frame changed. **Tested ✅** (`screenshots/video-playback.webp`)

**Copy frame.** Toast: `Frame copied`. **Tested ✅** (the toast; the clipboard payload was not independently inspected). This succeeded on a machine without xclip/wl-copy.

Playback of mkv / mov / webm, Expand player / Esc, and volume changes were **Not verified** beyond the mp4 session and the 80% default. Backend strings (ffmpeg `-ss … -vf scale… -r 24 -f image2pipe`; `FFmpeg was not found…`) are **Inferred (code or binary strings)**.

#### Audio

The Audio tab listed all four samples (`tone.wav`, `.flac`, `.mp3`, `.ogg`). **Tested ✅** (indexing). Cards can show a waveform strip (seen on first load).

**Player (tone.wav).** Play/pause, seek bar, time (`0:00 / 0:03`), volume (`80%`). Playback advanced and the waveform visualization changed. **Tested ✅**

flac / mp3 / ogg playback was **Not verified**. ffplay (`-nodisp -vn -autoexit -volume`) and ffmpeg `showwaves` / `showwavespic` (960 px) are **Inferred (code or binary strings)**.

#### Code

Opened individually from All files (search or card click): `README.md`, `data.json`, `hello.rs`, `live_edit.rs`, `notes.txt`, `script.py` — all render as syntax-coloured snippets / diffs, no crash. **Tested ✅** (`screenshots/p2-code-readme-card.webp`, `screenshots/p2-code-data-json-card.webp`, `screenshots/p2-code-live-edit-card-initial.webp`)

The **Code tab** itself crashed the app whenever it was opened, consistent with listing `mislabeled.jpg.txt` among code-type files. **Tested, failed ❌**

Syntax highlighting via syntect + two-face, and "N lines" labels, are **Inferred (code or binary strings)** as the engine; coloured snippets were observed.

### 2.9 Overview page

A project dashboard, switched from the sidebar. **Tested ✅** (`screenshots/overview.webp`)

Observed on the samples repo (3 commits, by design):

- Metrics: **Source lines** (10), **Commits** (3), **Active days** (1), **Review time** (about 8–9 minutes while the app was open in part 1; `project_seconds` later accumulated further).
- **Git activity** over the last 14 days; First / Latest commit; Busiest day; Peak hour; a **Commit hours** histogram.
- **Project makeup** ring: 62 files across Source, Data & scenes, Media, Documents, and Other.
- **Languages:** Rust and Python (10 total source lines in the view).
- **Storage:** total size and folder bars (models, `.git`, images, media, nested, watch_me, …). Clicking `models` drilled into child entries (large STL, `torus.obj`, `sphere.ply`, …). The `..` row returned to the parent. Binary copy says this list "Includes hidden and ignored folders."

**Copy menu:** **Copy image** and **Copy PDF**.

- Copy image → toast `Overview image copied`. **Tested ✅**
- Copy PDF → toast `Copy failed: No such file or directory (os error 2)`. **Tested, failed ❌** (may involve a temp path or clipboard helper; see §1.3).

Binary strings describe a single 800×1080 PDF page titled "INSPECTOR / PROJECT OVERVIEW", output names `Inspector-reports` / `Inspector-overview-*.png|pdf`, and `Report exceeds clipboard file size`. Those details are **Inferred (code or binary strings)**. Git command lines (`rev-list`, `log`, `ls-files`, `branch`, `--no-optional-locks`) and the auto-detected icon search list (`app.png`, `assets/icon.png`, …) are likewise **Inferred**, except that `assets/icon.png` was in fact used as the project icon (**Tested ✅**). **Refresh / Updating…** was **Not verified**.

### 2.10 Right-click menu

**File card (single selection).** Observed items: **Open file**, **Reveal in folder**, **Copy path**, **View details**. **Tested ✅** (`screenshots/p2-context-menu-single.webp`). Open / Reveal behaved as in §2.5. Copy path is present; the pasted value was not independently inspected, and there is no xclip/wl-copy on the box, so treat the clipboard write as **Not verified**. View details is the normal Inspector-panel workflow.

**Sidebar folder.** Observed: the folder path, **Copy path**, **Rescan folder**. **Tested ✅** (Rescan clicked on `images`).

**Items from binary strings not seen on a single-file menu:** `Copy collage`, `Copy clip to clipboard`, `Save clip as`, `Save review clip`, `Copy frame` (Copy frame lives on the video player, not this menu), `Remove project`, `Open folder`. Collage / review-clip actions appear to be aimed at a multi-selection, which could not be reached (see §2.14). **Not verified** in the GUI as menu items, except where part 1 reached Save clip / Save review clip through some earlier path and they failed (see §2.13).

Esc dismissed an open context menu. **Tested ✅**

### 2.11 Settings

Opened with **Ctrl+,**. Modal tabs: **Previews**, **Watching**, **Activity**, **Media**, **Sharing**; version **0.1.0**; a **Licenses** link. **Tested ✅** (`screenshots/settings-activity.webp`)

Values below are the defaults from `settings.default-empty.json` (and the same keys in `settings.after-cli-arg.json`, plus a filled `roots` entry). The GUI displayed the same numbers/toggles on open. One harmless test flipped **Animate new previews** Off and back On.

| Tab | UI label | JSON key | Default | Status |
|---|---|---|---|---|
| Previews | Preview memory | `preview_mb` | 256 MB | **Tested ✅** (displayed) |
| Previews | Versions per file | `versions` | 3 | **Tested ✅** (displayed; History cap also observed in use) |
| Previews | Preview resolution | `thumbnail_width` | 800 px | **Tested ✅** (displayed) |
| Previews | Decode memory limit | `decode_mb` | 128 MB | **Tested ✅** (displayed) |
| Previews | Preview history | — (Clear button) | Clear not used | Control **Tested ✅**; Clear **Not verified** |
| Watching | Respect .gitignore | `respect_gitignore` | On / `true` | **Tested ✅** (displayed; gitignored `ignored_by_gitignore` still visible because of the next toggle) |
| Watching | Include ignored media | `media_bypass_ignore` | On / `true` | **Tested ✅** (displayed; gitignored media appeared) |
| Watching | Tracked code files only | `tracked_only` | Off / `false` | **Tested ✅** (displayed) |
| Watching | Watch subfolders | `recursive` | On / `true` | **Tested ✅** (displayed; nested files appeared) |
| Watching | Maximum files | `file_limit` | 50k / `50000` | **Tested ✅** (displayed) |
| Activity | Follow new files | `follow_latest` | Off / `false` | **Tested ✅** (displayed); follow behavior **Not verified** |
| Activity | Update batching | `debounce_ms` | 250 ms | **Tested ✅** (displayed) |
| Activity | Activity history | `events` | 2048 events | **Tested ✅** (displayed) |
| Activity | Animate new previews | `animate_updates` | On / `true` | **Tested ✅** (displayed; toggled Off/On) |
| Media | Playback volume | `video_volume` | 80% | **Tested ✅** (displayed; player showed 80%) |
| Media | Playback resolution | `video_width` | 960 px | **Tested ✅** (displayed) |
| Sharing | Clip resolution | `share_height` | 720p / `720` | **Tested ✅** (displayed) |
| Sharing | Frame rate | `share_fps` | 24 fps | **Tested ✅** (displayed) |
| Sharing | Seconds per item | `share_seconds` | 2 sec | **Tested ✅** (displayed) |
| Sharing | Default destination | `share_clipboard` | UI showed **Clipboard**; dropdown also offered **File**. File default is `true`. Part 1 flagged this mapping as uncertain. | **Tested ✅** (control exists); key↔UI mapping **Not verified** with certainty |

**Keys present in the JSON but not found as a visible editor:**

| JSON key | Default | Notes | Status |
|---|---|---|---|
| `schema_version` | `2` | File format | **Tested ✅** (file) |
| `roots` | `[]` | Saved projects; CLI folder is appended | **Tested ✅** |
| `excludes` | `.git`, `node_modules`, `target`, `.venv`, `__pycache__`, `.local`, `.godot`, `.cache`, `.next`, `build`, `dist` | Default skip directory names. `.git`, `build`, and `node_modules` were unchecked/greyed in the sidebar. | **Tested ✅** (file + sidebar effect) |
| `hidden_extensions` | `import`, `uid`, `pyc`, `pyo`, `pdb`, `ilk`, `exp`, `tmp`, `temp`, `swp`, `swo`, `bak` | No UI editor found | **Inferred** as behavior; file **Tested ✅** |
| `folder_overrides` | `{}` | Later held per-folder include flags (e.g. images/media `true`) | **Tested ✅** (persisted during the session) |
| `project_seconds` | `{}` | Accumulates Overview "Review time" per project | **Tested ✅** (populated in use) |
| `sidebar_width` | `214.0` | Layout | **Tested ✅** (file); drag-resize **Not verified** |
| `inspector_width` | `340.0` | Layout | **Tested ✅** (file); drag-resize **Not verified** |

Binary strings also mention an **EXCLUSIONS** list (`Directory or *.extension`, Add, remove-exclusion) and a JSON key `exclusions`. No exclusions editor appeared in the five Settings tabs, even after scrolling. The saved file uses `excludes` and `hidden_extensions`, not an `exclusions` key. **Not verified** as a visible UI (strings are **Inferred**).

**Licenses.** Opens third-party notices (including Apache-2.0 / ring text), with **Back to settings** and version 0.1.0. **Tested ✅**. No separate Help/About menu was found in the chrome.

Binary strings mention `Back to settings` and update-batching / memory-limit error text (`Image exceeds the 64 MB de[code limit]`, `Preview exceeds the configured memory budget`). Those errors were **Not verified**.

### 2.12 Keyboard shortcuts

| Shortcut | Claimed / observed action | Status |
|---|---|---|
| **Ctrl+K** | Focus `Search files…`; typing filters the Feed | **Tested ✅** |
| **Ctrl+,** | Open Settings | **Tested ✅** |
| **Ctrl+O** | Add folder / project (binary: `inspector::AddFolder`) | **Tested, failed ❌** on this box — nothing visible (no picker backend) |
| **Ctrl+A** | Binary: `inspector::SelectAllFiles`; status bar would show `N selected · N images · …` | **Tested, failed ❌** in this environment — only ever a single selection, including after clicking a card or the Feed heading (`screenshots/p2-ctrl-a-no-selection.webp`). xdotool caveat applies. |
| **Esc** | Dismisses a context menu. In some states it cleared search and/or deselected the current card; with empty search, no extra effect. Binary also: close expanded player/preview. | **Tested ✅** for menu/search; expanded-preview Esc **Not verified** |
| **Arrow keys, Enter, Space** | Tried with a focused feed card; no visible navigation or action | No effect observed; **Not verified** as bindings |
| **Delete** | Intentionally not pressed | **Not verified** |
| **cmd-A / K / O / ,** | Same actions on macOS (binary strings) | **Inferred (code or binary strings)** — not a macOS box |

Text-field editing keys (backspace, delete, arrows, shift-select, ctrl-a/c/x/v, home/end) are **Inferred** from binary input bindings; ordinary typing in Search did work (**Tested ✅**).

### 2.13 Sharing and export

**Overview Copy image / Copy PDF.** See §2.9. Image copy toasted success; PDF copy failed with `Copy failed: No such file or directory (os error 2)`.

**Copy frame** (video player). Toast `Frame copied`. **Tested ✅**

**Save clip as.** In part 1, selecting it did not open a destination picker and produced no completion feedback (could not be aimed at `/workspace/inspector-study/out`). **Tested, failed ❌** — consistent with no file-picker backend on the box.

**Save review clip.** Part 1: exact error `No such file or directory (os error 2)`. **Tested, failed ❌**. Binary strings describe an `inspector-review.mp4` (libx264, concat, `+faststart`), a 1–24 image-or-video selection (`Select between 1 and 24 files for a review clip`, `Review clips support images and videos`), and errors about size limits, cancel, and missing FFmpeg. Those details are **Inferred**. Multi-select could not be used to reach this path in part 2.

**Copy collage / Copy clip to clipboard.** Binary: collage of 1–24 images, 3D models, or video frames; clipboard via `wl-copy --type text/uri-list` or `xclip -selection clipboard`. Not present on the single-file menu; multi-select was not reached. **Not verified** (and the box has neither clipboard helper).

Sharing settings (clip resolution 720p, 24 fps, 2 seconds per item, default destination) exist and show the defaults above. End-to-end clip generation was **Not verified** (the attempted saves failed before a file appeared).

### 2.14 Multi-select

Binary bindings and status-bar copy describe multi-select (`inspector::SelectAllFiles`, `N selected · N images · N models · N audio/video`), which would be the doorway to Copy collage and a 1–24 review clip.

In the GUI, **Ctrl+click**, **Shift+click**, and **Ctrl+A** (focus on the page, after clicking a card, and on the Feed heading) only ever selected one card. No selection count, action bar, or status-bar "N selected" appeared (`screenshots/p2-ctrl-click-no-multiselect.webp`, `screenshots/p2-shift-click-no-multiselect.webp`, `screenshots/p2-ctrl-a-no-selection.webp`).

**Tested, failed ❌** in this environment. Because modifiers were sent through xdotool, the feature may still exist and simply have been unreachable here. It is also listed under §7 as not confirmed working.

---

## 3. Supported file types

How each app treats the sample types (and a few extras that only appear in code or binary strings). Inspector results are from the GUI unless noted. Live Gallery type coverage is from source, with HTTP checks on Ryan's running instance for counts and API — individual sample files were not opened in Live Gallery's viewer.

| Kind | Extension / sample | Inspector | Live Gallery |
|---|---|---|---|
| Raster | `.png` (including alpha, tiny 1×1, tall, wide, unicode name) | Image preview. **Tested ✅** | Watched and shown in the grid; the original file is the thumb. **Inferred (code)** for the viewer; types are in the watched set (**Inferred**), instance had 35,102 images (**Tested ✅**). |
| Raster | `.jpg` / `.jpeg` (including 6000×4000) | Image preview. **Tested ✅** | Same as PNG. **Inferred (code)** |
| Raster | `.webp` still | Image preview. **Tested ✅** | Watched; browser would animate animated WebP. **Inferred (code)** |
| Raster | `.webp` animated | Static frame 0; does not animate. **Tested, failed ❌** | Browser-animated in the grid. **Inferred (code)** — not clicked. |
| Raster | `.gif` still | Image preview. **Tested ✅** | Watched. **Inferred (code)** |
| Raster | `.gif` animated | Static frame 0; does not animate. **Tested, failed ❌** | Browser-animated in the grid. **Inferred (code)** — not clicked. |
| Raster | `.bmp` | Image preview. **Tested ✅** | Watched. **Inferred (code)** |
| Raster | `.tiff` | Image preview. **Tested ✅** | **Not in the watched extension list.** **Inferred (code)** — would be ignored by the watcher. |
| Raster | `.svg` | Syntax-coloured source, type Text; not a graphic. **Tested ✅** | Watched as an image; the browser would render it. **Inferred (code)** |
| Raster | `.ico` | Generic File card. **Tested ✅** (fallback) | Watched as an image. **Inferred (code)** |
| Raster | `.avif` | Only mentioned in a gpui image list; no sample. **Not verified** / decode **Inferred** as uncertain | Watched as an image. **Inferred (code)** |
| Raster | `.tga` | Generic File card. **Tested ✅** (fallback) | Not in the watched list. **Inferred (code)** — ignored. |
| Raster | `.ppm` / PNM | Generic File card. **Tested ✅** (fallback) | Not in the watched list. **Inferred (code)** — ignored. |
| Raster | `.exr` (OpenEXR) | Generic File card. **Tested ✅** (fallback) | Not in the watched list. **Inferred (code)** — ignored. |
| Raster | `.hdr` (Radiance) | Generic File card. **Tested ✅** (fallback) | Not in the watched list. **Inferred (code)** — ignored. |
| Raster | DDS, farbfeld, QOI, PCX | Compiled into Inspector's image crate list. **Inferred**; no samples. **Not verified** | Not in the watched list. **Inferred (code)** |
| Raster | `corrupt.png` | Preview unavailable + a decoder error; no crash. **Tested ✅** | Failed image loads show `EXT / can't display`. **Inferred (code)** |
| Raster | `mislabeled.jpg.txt` (PNG bytes, `.txt` name) | Treated as code; rendering the card panics cosmic-text. **Tested, failed ❌** | Ignored (not an image/3D extension). **Inferred (code)** |
| 3D | Binary `.stl` | Renders (including a ~330k-triangle sphere on the card, and live-updated `model_change.stl`). **Tested ✅** | Watched; three.js STLLoader. **Inferred (code)** |
| 3D | ASCII `.stl` | `Only binary STL is supported`. **Tested, failed ❌** as a mesh | Watched; three.js typically loads ASCII STL. **Inferred (code)** — not tested on this sample. |
| 3D | `.obj` with triangles | Renders (`torus.obj`, 2048 triangles). **Tested ✅** | Watched; OBJ loader. **Inferred (code)** |
| 3D | Empty `.obj` | `Model has no supported triangles`. **Tested, failed ❌** as a mesh | Would be watched; viewer error path **Inferred (code)** |
| 3D | `.glb` | Renders (`sphere_colored.glb`) but vertex colour showed grey. **Tested ✅** / colour **Tested, failed ❌** | Watched; GLTF loader + Draco/Meshopt. **Inferred (code)** |
| 3D | `.gltf` + external `.bin` in the same folder | Renders. **Tested ✅** | Watched. **Inferred (code)** |
| 3D | `.gltf` with embedded / data-URI buffers | `Embedded or remote buffers are not supported`. **Tested, failed ❌** | three.js GLTFLoader generally supports embedded buffers. **Inferred (code)** — not tested here. |
| 3D | Broken `.glb` | `failed to fill whole buffer` / Preview unavailable. **Tested, failed ❌** as a mesh | Watched; viewer error **Inferred (code)** |
| 3D | `.ply` | Listed in the 3D tab; preview refused (`Preview supports GLB, glTF, OBJ and binary STL.`). **Tested, failed ❌** | Watched; PLY loader; unindexed PLY as a **point cloud**; vertex colours honored. **Inferred (code)** |
| 3D | `.fbx` | Not in the supported-preview string; no sample file. **Not verified** (almost certainly unsupported) | Watched; FBX loader. **Inferred (code)** |
| 3D | `.3mf` | Not listed in the 3D tab. **Not verified** (not treated as 3D in the tab count) | Not in the watched list. **Inferred (code)** — ignored. |
| Video | `.mp4` | Indexed; card frame; player plays. **Tested ✅** | Ignored by the watcher. **Inferred (code)** |
| Video | `.mkv`, `.mov`, `.webm` | All four appear in the Video tab; mov/mkv showed a frame on load. Playback **Not verified** except as indexed. | Ignored. **Inferred (code)** |
| Audio | `.wav` | Indexed; waveform; player plays. **Tested ✅** | Ignored. **Inferred (code)** |
| Audio | `.flac`, `.mp3`, `.ogg` | All appear in the Audio tab. Playback **Not verified**. | Ignored. **Inferred (code)** |
| Code | `.rs`, `.py`, `.md`, `.json`, `.txt` | Syntax-coloured card + panel; Compare unified diff for edited `.rs`. **Tested ✅** | Ignored. **Inferred (code)** |
| Other | `.bin` (glTF buffers) | In the models folder count, not as previewable 3D items. **Tested ✅** (not in the 3D tab's 11) | Ignored unless a watched extension. **Inferred (code)** |
| Other | `.log`, `.gitignore` | Not specifically opened. Initial Feed was 61 files; these may or may not be included. **Not verified** | Ignored. **Inferred (code)** |
| Other | Dotfiles with no stem (e.g. `.png`) | — | Ignored. **Inferred (code)** |

Extension matching in Live Gallery is case-insensitive (**Inferred (code)**). Inspector's case rules were **Not verified** (samples used lowercase extensions).

---

## 4. Live Gallery feature summary by area

Full detail, including HTTP routes and security notes, lives in `live-gallery-features.md`. This is a compact map, with status as defined in §1.

### 4.1 Command line and process

`live-gallery [DIR ...] [--default DIR] [-p/--port N] [-i/--interval SECS] [-n/--initial N] [-x/--exclude NAME]... [--poll] [--host H] [--open]`

| Flag | Behavior | Status |
|---|---|---|
| `DIR ...` | Folders to watch. If none, uses `state.json` `roots`, then `--default`, then `.`. Invalid dir → exit 1. Nested duplicates dropped. `~` expanded, paths made absolute. | **Inferred (code)**; running roots came from `state.json` recent[0], not `--default`. **Tested ✅** |
| `--default DIR` | Fallback until a folder is picked in the page. | **Tested ✅** (present on the running process) |
| `-p` / `--port` | Default tries 8765–8784; explicit taken port → `port unavailable`, exit 1. | **Inferred (code)**; running port 29024 **Tested ✅** |
| `-i` / `--interval` | Polling interval, default 1.0 s. | **Inferred (code)** |
| `-n` / `--initial` | Page size, default 60, clamped 1–500. | **Tested ✅** (`no limit` → 60 items; `limit=999` → 500) |
| `-x` / `--exclude` | Skip folders with this exact name; repeatable. | **Inferred (code)** |
| `--poll` | Poll instead of inotify. | **Inferred (code)** |
| `--host` | Bind address, default 127.0.0.1. | **Tested ✅** (running on 127.0.0.1) |
| `--open` | Open the browser at the URL. | **Inferred (code)** |

Logs `Live Gallery: http://localhost:PORT/`, indexing/watching lines, and `[HH:MM:SS] add\|update /abs/path` per change. Ctrl+C stops it. **Inferred (code)**

Lantern integration (`lantern.yaml`, id `livegallery`, health `/api/list`) matches the running process args. **Tested ✅** (args); yaml itself **Inferred (code)**

### 4.2 Folder watching

Linux **inotify** (one watch per folder: CLOSE_WRITE, MOVED_FROM/TO, CREATE, DELETE, ONLYDIR, DONT_FOLLOW, EXCL_UNLINK). Running: `mode = "inotify, 175285 folders"`. **Tested ✅** (mode string). Watch-before-list, ENOSPC warning, polling fallback (macOS/Windows/`--poll`/inotify failure), two-scan settle, 1 s write-settle, add-vs-update 5 s threshold, delete/move removal, Q_OVERFLOW rescan: **Inferred (code)**.

**Built-in skip list:** `.git node_modules __pycache__ .venv venv .mypy_cache .pytest_cache .tox .cache cache Cache site-packages vendor target .godot .import tool_profiles app_userdata`, plus `-x` names. **No `.gitignore` support.** Hidden folders other than that list **are** scanned. Symlinked dirs are not followed. **Inferred (code)**

Changing watched folders bumps a generation, stops the old watcher (~50 ms), and broadcasts `reset`. **Inferred (code)**

### 4.3 Web UI (header)

Served assets were byte-identical to source (**Tested ✅**), but these widgets were not clicked, so behavior is **Inferred (code)** unless noted.

- Title + status dot (green live SSE / red retry). Tooltip: `Live · inotify, N folders` or `polling every 1s`.
- **Folder chips:** shortest unique path suffix; with 2+ roots, click isolates a folder, **×** unwatches; a single-root chip is inert and has no ×.
- **Add a folder…** path box, comma-separated, subdirectory autocomplete via `GET /api/dirs` (120 ms debounce). **`/api/dirs` responds: Tested ✅.**
- Status: `indexing…`, `switching…`, errors, or `↑ N new files` (click scrolls to top).
- **All / Images / 3D** filter (`kind=`). **Tested ✅** (`kind=model` → 1803, `kind=image` → 35102).
- **Filter by path** (`#q`, `/` focuses it), 160 ms debounce, server-side `q=`. **Tested ✅** (`q=selfcheck` → 17).
- Thumbnail size slider 120–420 px, default 200, saved in `localStorage['lg-size']`.
- **Follow** toggle: each new arrival opens full-size in the viewer.
- **Pause / Resume (N new):** holds add/update events; removes still apply; resume replays held events.
- Count: `N files` or `N of TOTAL`.
- Bookmarkable `?watch=/a,/b`; URL rewritten after folder changes.
- Tab title `Live Gallery · labels`; hidden tab becomes `(N) Live Gallery · …`.
- Light/dark via `prefers-color-scheme`; `prefers-reduced-motion` disables animations.

### 4.4 Grid, cards, thumbnails, viewer

All **Inferred (code)** except where an HTTP check is noted.

- CSS grid, newest first (arrival time `at`, then mtime, then id). Ordering **Tested ✅** via the list API.
- Infinite scroll with `before` / `before_m` / `before_id`. Cursor paging **Tested ✅**.
- Card: checkerboard thumb, extension badge, name, folder (click filters to it), relative age, size. **NEW** (green) / **UPDATED** (amber) tags and a glow that fades after 20 s.
- Live-event batching (40 ms coalesce; >20 events wait up to 1.5 s; >60 triggers a full reload). If scrolled down more than one screen, shows `↑ N new files` instead of jumping.
- Memory cap: trim back to 300 cards past 420 at the top.
- Image thumbs = the original file (`?v=mtime`, long cache). Headers **Tested ✅**.
- 3D thumbs: 512² three.js, Worker + OffscreenCanvas when possible, 180 s timeout, lazy near-view render, POST to `/api/thumb`, cache `~/.cache/live-gallery/thumbs/<sha1>`. List API `thumb: true` and `GET /t/<key>` **Tested ✅** (Ryan's cache had 3,680 thumbs). POST itself was not exercised (would write the cache).
- **Viewer (lightbox):** ←/→, path, zoom %, **Watch only this folder**, **Copy path**, Esc. Images: fit/100%/wheel-zoom up to 16×, drag pan, keys `1` and `0`. 3D: OrbitControls (orbit, scroll zoom, right-drag pan), room lighting, auto-frame. three.js from CDN, so 3D needs internet the first time; images work offline.

### 4.5 HTTP API, state, security

See the route table in `live-gallery-features.md` §9. GETs of `/`, assets, `/api/list` (including clamp/fallback), `/api/dirs`, `/events` (`: hi`), `/f/…`, `/t/…` were **Tested ✅**. `POST /api/thumb` and `POST /api/watch` were **not** exercised (they would write Ryan's cache or change his watched set) — **Inferred (code)**.

State: `~/.config/live-gallery/state.json` (`roots` + `recent`, last 12 sets, atomic write). File exists; API `recent` had 11 entries. **Tested ✅**. No settings UI, no file-version history, no compare, no export.

Security notes from the Live Gallery inventory (kept here only as observed behavior, not a fix list): default bind 127.0.0.1 (**Tested ✅**); path traversal `../` and `%2e%2e` on `/f/` → 404 (**Tested ✅**); `/f/` will serve any existing file under a watched root, not only image/3D (**Tested ✅**, status only); no Host/Origin check (**Tested ✅** with a `Host: evil.example` request → 200); no auth; 3 MiB POST caps (**Inferred (code)**).

### 4.6 What Live Gallery does not include

No video, audio, or code support; no version history or compare; no project Overview / git dashboard; no settings UI; no review-clip or report export. Those are Inspector additions (see §5).

---

## 5. Comparison

### 5.1 Shared features

Both are local, folder-watching galleries for following generated output (agents, builds, renders), newest first.

| Feature | Live Gallery | Inspector |
|---|---|---|
| Recursive folder watch | Yes (inotify or poll) | Yes (`recursive` / Watch subfolders) |
| Multiple roots / projects | Yes (chips, `?watch=`, `state.json`) | Yes (`roots` in settings; one project used in testing) |
| Live add / update without refresh | Yes (SSE) | Yes (native watcher) |
| Live removal | Yes (cards removed) — **Inferred (code)** | Yes (Removed row, count drop) — **Tested ✅** |
| Pause incoming adds/updates | Yes — **Inferred (code)** (removes still apply) | Yes — **Tested ✅** (new file held; some already-visible text still refreshed) |
| Newest-first grid of images | Yes | Yes |
| Path/name filter | Yes (`q=`, `/` focuses) — API **Tested ✅** | Yes (Search / Ctrl+K) — **Tested ✅** |
| Type filter: images vs 3D | Yes (All / Images / 3D) | Yes, plus Video / Audio / Code |
| Common image previews (PNG, JPEG, WebP, GIF, BMP) | Yes (browser) | Yes (native) |
| 3D: GLB, glTF (external bin), OBJ, binary STL | Yes (three.js) | Yes (built-in viewer) |
| Hidden folders included (except a skip list) | Yes | Yes (`.hidden_dir` appeared) |
| Default skip of `.git`, `node_modules`, `build` / `target`, etc. | Fixed skip list | `excludes` + optional `.gitignore` |
| "New items" affordance when scrolled down | `↑ N new files` | **New changes ↑** pill |
| Follow-new-files option | Follow toggle | Settings **Follow new files** (default Off) |
| Open/reveal a path on disk | Copy path; files served at `/f/` | Open file / Reveal in folder / Copy path |
| Persisted roots | `state.json` | `settings.json` `roots` |

### 5.2 Inspector additions

Features observed in Inspector that Live Gallery does not have:

- Native GPUI/Vulkan desktop app (no browser, no CDN for 3D).
- File-type tabs for **Video, Audio, and Code**, plus syntax-highlighted code cards and a unified code diff.
- **Video and audio playback** (ffmpeg/ffplay/ffprobe), waveforms, **Copy frame**.
- Right-hand **Inspector** panel: Details, **version History** (capped, in-session), **Compare** (Before/Now image slider; code diff).
- **Live activity** timeline with range presets, tick filtering, **Back to latest**, pause, and Added/Updated/Removed event rows.
- Sidebar **per-folder include** checkboxes and **Rescan folder**.
- **`.gitignore` awareness** and **Include ignored media**.
- **Overview** dashboard: git metrics, languages, storage drill-down, project icon, Copy image / Copy PDF.
- A full **Settings** dialog (preview memory and versions, watching, activity, media, sharing).
- Sharing/export surface (review clip, collage, Copy image/PDF, Save clip as) — several of these did not complete on the box, but the UI and strings are there.
- Multi-select and batch share (claimed in the binary; **not triggered** here).
- Status bar with project/file counts and Watching / Paused / Ready.
- Grid **and** list view, Newest/Oldest sort toggle.

### 5.3 Live Gallery features missing from Inspector, or narrower in Inspector

- **PLY and FBX** previews (Live Gallery; Inspector refused PLY and does not claim FBX).
- **ASCII STL** (Inspector rejects it; Live Gallery's three.js loader would typically accept it — not tested on the sample).
- **Embedded / data-URI glTF** (Inspector rejects; three.js generally supports this — not tested in Live Gallery here).
- **Vertex colours** on a GLB (Inspector rendered the coloured sphere grey). Live Gallery claims vertex colours for STL and PLY — **Inferred (code)**.
- **Animated GIF/WebP** actually animating (browser in Live Gallery — **Inferred**; Inspector stayed on frame 0).
- **SVG as a graphic**, and **ICO** as an image (Inspector: SVG as text, ICO as a generic File).
- **AVIF** in the watched set (Live Gallery; Inspector uncertain / untested).
- **In-viewer image zoom and pan** (Live Gallery lightbox; not observed in Inspector's panel; an expanded preview is only in Inspector's binary strings).
- **3D scroll-zoom / right-drag pan** (documented for Live Gallery's OrbitControls; Inspector rotate worked, zoom/pan were not observed).
- **3D thumbnails via a worker**, cached as WebP, with a CDN-backed viewer (Inspector builds native thumbs/previews instead).
- **Multiple roots visible at once** as chips, with `?watch=` bookmarkable URLs, recent-folder autocomplete, and "Watch only this folder." Inspector is project-based; adding a second project was not possible on the box (no picker) and was **Not verified**.
- **HTTP API / SSE** and a simple local web server (anyone on the bind address can open the grid). Inspector is a single-machine GUI.
- **Infinite scroll** over very large sets (Ryan's instance: tens of thousands of files). Inspector has a configurable `file_limit` (default 50k) and a cap warning in strings; large-set behavior was **Not verified**.
- **Thumbnail size slider**, tab-title unseen-count, `prefers-color-scheme` / reduced motion (web UI).
- A **Python reference implementation** alongside the Rust server.

TIFF, TGA, EXR, HDR, and PPM go the other way: Inspector at least indexes them (TIFF/BMP preview; the others as generic files); Live Gallery's watcher ignores those extensions.

### 5.4 Differences in watching and scope

- Live Gallery watches **only images and 3D**. Inspector indexes **images, 3D, video, audio, and code** (and some generic files).
- Live Gallery has a **fixed skip list** and no `.gitignore`. Inspector **Respect .gitignore** (default On) plus **Include ignored media** (default On), and a longer default `excludes` list (`dist`, `.next`, `.local`, …).
- Live Gallery skip list is not editable in a settings UI; Inspector stores `excludes` / `hidden_extensions` in JSON, but no exclusions editor was found in the Settings tabs.
- Live Gallery announces a file as `add` vs `update` with a 5 s rule and a write-settle queue. Inspector uses `debounce_ms` (250) and shows Added / Updated / Removed in the Feed and timeline. The exact Inspector settle rules were **Not verified** beyond the successful live-update tests.
- Live Gallery can bind to a host/port and is a web service (with the security properties noted in `live-gallery-features.md`). Inspector is a desktop process with a settings file under `~/.config/Inspector/`.

---

## 6. Broken, confusing, or incomplete (observations only)

These are things that did not work as the UI or labels suggest, or that were easy to misread. They are recorded so the feature set is honest. They are not a to-do list.

**App crash on `images/mislabeled.jpg.txt`.** That file is a PNG saved with a `.txt` extension, so Inspector treats it as code/text. Anything that renders its card kills the process: searching `mislabeled` (reproduced three times in part 2) and switching to grid after an `images/` filter. Opening the **Code tab** also crashed, consistent with that file being in the code list. Panic in `run.log`:

```
thread 'main' panicked at .../cosmic-text-0.14.2/src/shape.rs:895:13:
assertion `left == right` failed
  left: true
  right: false
```

Likely trigger: text-shaping of binary PNG bytes (control characters) displayed as text. The same session showed that `corrupt.png` (error text that itself contains control characters), the unicode filename, and SVG source **did not** crash, and that opening `README.md`, `data.json`, `hello.rs`, `live_edit.rs`, `notes.txt`, and `script.py` from All files is fine. `run.log` recorded six of these panics. After a restart, in-session History was gone (see below). Screenshots: `screenshots/p2-crash-mislabeled-search.webp`, `screenshots/p2-run-crash.log`.

**ASCII STL does not preview.** `cube_ascii.stl` shows `Only binary STL is supported`.

**PLY (and likely FBX / 3MF) do not preview.** `sphere.ply` shows the GLB/glTF/OBJ/binary-STL support line. `cube.3mf` did not appear in the 3D tab.

**Some glTF/GLB paths do not preview.** `embedded_datauri.gltf`: embedded/remote buffers unsupported. `broken.glb`: `failed to fill whole buffer`. `empty.obj`: no supported triangles. These are understandable failure messages; they are listed because they are part of the observed preview surface.

**Coloured GLB rendered grey.** `sphere_colored.glb` drew 1280 triangles without visible vertex colour.

**Animated GIF and WebP do not animate.** Card and panel stayed on frame 0 for minutes (`screenshots/p2-img-animated-gif-static-frame0.webp`).

**No image zoom in the panel.** Wheel did nothing; no zoom controls. An expanded preview is only known from binary strings.

**3D zoom and pan not observed.** Rotate works; scroll zoom and right-drag pan were not visible (software Vulkan is a possible factor). Reset view is present; full restore-after-orbit was not firmly rechecked in part 2.

**New changes pill click can land on a card.** The pill scrolled to the top, but the selection jumped to `openexr.exr`, the card under the click after the layout shifted (`screenshots/p2-after-pill-click-exr-selected.webp`). New cards inserting at the top also shift layout under the cursor.

**History is in-session only.** Revisions cap at 3, and a crash/restart left only Current. Nothing in the tested UI suggested they would be persisted, but it is easy to assume they would be.

**Multi-select was unreachable.** Ctrl+click, Shift+click, and Ctrl+A never produced a multi-selection or "N selected" status, so collage / review-clip actions that need 1–24 files could not be used. xdotool may have been involved; the bindings exist in the binary.

**Add project / Ctrl+O silent.** No dialog, no error. Almost certainly the missing folder-picker backend on the box (§1.3), but from the user's seat it is just a no-op (`screenshots/p2-after-ctrl-o-nothing.webp`, `screenshots/p2-after-add-project-click-nothing.webp`).

**Save clip as: no picker.** Same class of observation as Add project.

**Save review clip and Copy PDF:** both returned `No such file or directory (os error 2)` (PDF toast: `Copy failed: …`). Copy image and Copy frame on the same machine toasted success, so this is not a blanket "clipboard is dead" result. Missing helpers or a temp path may be involved (§1.3).

**Open file / Reveal in folder go through Chrome.** A local directory index (and one download) rather than a native editor or file manager. The app stays in the taskbar. This is the box's `xdg-open` handler, but it is what the buttons did here.

**SVG is text; ICO / EXR / HDR / TGA / PPM are generic Files.** Even though several of those codecs are mentioned in the binary, the samples did not preview as images. Confusing if you expect "supported image format" to mean a thumbnail.

**Code tab is unsafe on this sample set** because of the mislabeled file, even though ordinary code files are fine.

**Settings exclusions UI not found.** Defaults clearly apply (`.git` / `build` / `node_modules` greyed), but there was no editor in the five tabs. Binary strings still talk about an EXCLUSIONS list. **Default destination** vs `share_clipboard` was flagged as an uncertain mapping.

**`--help` is silent.** The process just opens the GUI. A second CLI path is ignored. A report-export mode is hinted in strings but was not reached.

**Feed count vs file count.** `Feed N` can count change events, not only current files.

**Pause is partial.** New files are held; an already-visible code card can still refresh, and Updated-now badges can clear.

**Compare slider not dragged; Before/Now on `will_change.png` both looked red** because every script round rewrites that file to red. The control is there; a visually obvious image diff was not captured.

---

## 7. Tested vs inferred vs not verified

### 7.1 Tested ✅ (worked as described)

**Inspector, GUI and launches**

- Opening the GUI, empty state, and loading `/workspace/inspector-study/samples` via a positional CLI argument (written to `roots`).
- `--help` / `-h` open the GUI and print no help (the silence is the observed behavior).
- Multiple instances can run; `settings.json` is created and updated.
- Layout: top bar, search, sidebar Feed/Overview/FOLDERS, Inspector panel, Live activity strip, status bar (Ready / Watching / Paused, project and file counts).
- Search (Ctrl+K), Settings (Ctrl+,), Licenses, grid/list toggle, Newest/Oldest sort, type tabs and counts (except the Code tab crash), folder counts, nested files, hidden dir included, default-excluded dirs greyed, gitignored media included.
- Live add/update (no refresh), badges, re-sort, selection retained, panel revision on the selected file, New changes pill (appears and scrolls up), pause/resume catch-up, timeline range menu, tick filter, Back to latest, Removed row, 10-file burst as 10 cards.
- Details; History (3-revision cap, live model revisions); Compare UI (Before/Now slider present; code unified diff, including Previous · 2).
- 3D: binary STL (including live `model_change.stl`), `torus.obj`, `sphere_colored.glb` mesh, `scene.gltf`+`.bin`, `bracket.stl`, big-sphere card thumb; left-drag rotate; Reset view button present.
- Images that previewed: PNG (including unicode name, alpha, odd aspect ratios, 1×1), JPEG (including 6000×4000), still WebP/GIF, TIFF, BMP; `corrupt.png` error without a crash.
- Video: `clip.mp4` playback, Copy frame toast; Audio: `tone.wav` playback and waveform; Video/Audio tabs index all eight media samples.
- Code files opened one-by-one from All files (highlighting, live_edit updates).
- Overview metrics, git activity, languages, storage drill-down, project icon from `assets/icon.png`, Copy image toast.
- Context menu (file and folder), Rescan folder, Esc dismisses the menu.
- Settings defaults as displayed (and Animate new previews toggle Off/On).
- Open file and Reveal in folder do launch *something* (Chrome, in this environment).

**Live Gallery, HTTP / process**

- Running Rust server, host/port/args, asset bytes identical to source, `state.json` / recent, inotify mode and folder count, list API (paging, kind, q, limit clamp), `/api/dirs`, SSE `: hi`, `/f/` and `/t/` fetches, traversal rejection, image/model totals, thumbnail cache presence, default bind 127.0.0.1.

### 7.2 Tested, failed ❌ (exercised, did not do the expected thing)

- Code tab, and any path that renders `mislabeled.jpg.txt`, crash with the cosmic-text assertion.
- ASCII STL, PLY, embedded-data-URI glTF, broken GLB, empty OBJ: no mesh preview (error text as in §2.7).
- Vertex colour on `sphere_colored.glb` not applied (mesh is grey).
- Animated GIF/WebP stay on frame 0.
- Ctrl+O and Add project… : no picker, no error (box has no picker backend).
- Save clip as: no picker, no completion.
- Save review clip and Copy PDF: `No such file or directory (os error 2)`.
- Ctrl+A / Ctrl+click / Shift+click: no multi-select UI (xdotool caveat in §1.3 and §7.3).
- In-panel image zoom: wheel does nothing.

"Failed" here includes environment-blocked actions (picker, some exports). It does not mean the product would fail the same way on a desktop with a portal, zenity, and clipboard helpers.

### 7.3 Inferred (code or binary strings)

- Inspector modules, GPUI 0.2.2, ffmpeg/ffplay/ffprobe command lines, syntect/two-face, `similar` diffs, rfd/portal/zenity picker, wl-copy/xclip, git command lines for Overview, report PDF page size/title, review-clip encode settings, file-cap warning, folder-limit 32, many status-bar strings, expanded preview zoom controls, macOS cmd- shortcuts, compiled image codecs not seen in the UI, model 64 MB cap, `exclusions` UI copy, headless report-export strings.
- Live Gallery: almost all UI widget behavior (chips, Follow, Pause, lightbox zoom/orbit, batching rules, skip list, settle/add-update rules, POST routes, security write paths not hit), Python reference script, three.js loader capabilities (PLY point clouds, FBX, ASCII STL, vertex colours, embedded glTF).

### 7.4 Not verified

- Drag-and-drop "Drop a folder anywhere"; adding a second project when a picker exists; Remove project; switch-project.
- Headless PNG/PDF report CLI (the guessed argv did not write a file).
- Multi-select and Copy collage, when modifiers are delivered natively (not via xdotool).
- Follow new files (setting left Off); Clear preview history; exclusions editor; sidebar/inspector resize; file-limit cap warning.
- Timeline mouse-wheel (no effect, but maybe none is intended).
- Before/Now slider dragging; a visually obvious image diff; 3D History compare as a visual diff; Reset view fully restoring an orbit.
- 3D scroll-zoom and right-drag pan (no visible change).
- Expanded image/video preview (zoom in/out/fit/100%, Esc).
- Playback of mkv/mov/webm and flac/mp3/ogg; volume adjustment; Expand player.
- Copy path / Copy image / Copy frame *payloads* (toasts or menu items only); clipboard collage.
- AVIF, DDS, QOI, PCX, farbfeld; 3MF as a type; FBX in Inspector; Inspector case-insensitive extensions; Delete key; arrow/Enter/Space navigation.
- Settings keys' effect when changed, other than Animate new previews' toggle being reversible and Versions = 3 matching History.
- `share_clipboard` ↔ Default destination mapping (flagged uncertain).
- Status strings such as Scanning, File watcher unavailable, Folder limit reached, Project scan timed out.
- Live Gallery UI as clicked in a browser (including animation, zoom, Follow, Pause, chips, lightbox). POST `/api/watch` and `/api/thumb`.

**Intentionally not tried:** deleting files by hand in the UI, Remove project, Preview history Clear, and other destructive settings edits. The live script's own file delete was used to observe the Removed row.

---

## 8. Notes for building something similar

Core feature set that showed up in these two apps, without designing a new one:

- Watch one or more project folders recursively and surface new, changed, and removed files in a newest-first gallery, without a manual refresh.
- Pause the stream, keep a short activity timeline, and let the user jump back to latest.
- Filter by type and by path/name, with both a dense grid and a path-oriented list.
- Preview the formats the workflow actually produces: images and 3D at minimum; Inspector also covers video, audio, and syntax-highlighted code.
- A details side panel, and (in Inspector) short in-session version history with a before/now compare.
- Practical watch rules: skip lists, optional `.gitignore`, include-ignored-media, per-folder include, recursive nested output.
- Open or reveal the real file on disk so the user can point at it in the wider toolchain.
- A small settings surface (memory, version cap, media, follow-new) and persisted roots.

That is the observed ground, not a specification.
