#!/usr/bin/env python3
"""Antigravity 2.0 Live Gallery sidecar server.

Streams agent-created 3D models, images, videos, audio, code, text, artifacts,
and agent responses in real time inside Antigravity's Auxiliary (Side) Pane or
any standalone browser.

Standard library only (Python 3.8+). Uses Linux inotify when available and falls
back to lightweight polling elsewhere.
"""
import argparse
import atexit
import ctypes
import ctypes.util
import datetime
import errno
import hashlib
import heapq
import json
import mimetypes
import os
import queue
import re
import select
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico"}
MODEL_EXT = {".glb", ".gltf", ".obj", ".stl", ".ply", ".fbx"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
CODE_EXT = {
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".c",
    ".cpp", ".cc", ".h", ".hpp", ".java", ".rb", ".sh", ".bash", ".zsh",
    ".css", ".scss", ".html", ".htm", ".json", ".yaml", ".yml", ".toml",
    ".xml", ".sql", ".glsl", ".wgsl", ".gd", ".cs", ".swift", ".kt", ".zig",
    ".lua", ".nix", ".vue", ".svelte", ".proto", ".graphql",
}
TEXT_EXT = {".md", ".markdown", ".txt", ".csv", ".tsv", ".log", ".pdf"}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".cache", "cache",
    "Cache", "site-packages", "vendor", "target", "dist", "build", ".next",
    ".nuxt", ".turbo", ".godot", ".import", "tool_profiles", "app_userdata",
    ".system_generated", "chunks", "browser_sandbox",
}

for _ctype, _ext in [
    ("model/gltf-binary", ".glb"),
    ("model/gltf+json", ".gltf"),
    ("model/stl", ".stl"),
    ("image/webp", ".webp"),
    ("image/avif", ".avif"),
    ("image/svg+xml", ".svg"),
    ("video/mp4", ".mp4"),
    ("video/webm", ".webm"),
    ("video/quicktime", ".mov"),
    ("audio/mpeg", ".mp3"),
    ("audio/wav", ".wav"),
    ("audio/ogg", ".ogg"),
    ("audio/flac", ".flac"),
    ("application/pdf", ".pdf"),
]:
    mimetypes.add_type(_ctype, _ext)

THUMB_MAX = 2 * 1024 * 1024
TEXT_PREVIEW_BYTES = 1600
TEXT_MODAL_MAX_BYTES = 256 * 1024
MAX_WORKSPACE_ITEMS = 2500
MAX_PER_ROOT = 500
MAX_SCAN_DIRS_PER_ROOT = 4000
MAX_BRAIN_CONVOS = 24
MAX_AGENT_CARDS = 400
IMMUTABLE = "private, max-age=31536000, immutable"


def kind_of(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT:
        return "image", ext
    if ext in MODEL_EXT:
        return "model", ext
    if ext in VIDEO_EXT:
        return "video", ext
    if ext in AUDIO_EXT:
        return "audio", ext
    if ext in CODE_EXT:
        return "code", ext
    if ext in TEXT_EXT:
        return "text", ext
    return None, ext


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "live-gallery")


def thumbs_dir():
    d = os.path.join(cache_dir(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return d


def state_file():
    data_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "state.json")
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(cfg, "live-gallery")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "antigravity-state.json")


def runtime_files():
    files = [os.path.join(cache_dir(), "sidecar-runtime.json")]
    data_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if data_dir:
        files.append(os.path.join(data_dir, "runtime.json"))
    return files


def write_runtime_info(port):
    payload = json.dumps({
        "port": port,
        "pid": os.getpid(),
        "started_at": time.time(),
    })
    for path in runtime_files():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError:
            pass


def cleanup_runtime_info():
    pid = os.getpid()
    for path in runtime_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
            if info.get("pid") == pid:
                os.unlink(path)
        except Exception:
            pass


def parse_iso_ts(val):
    if not val or not isinstance(val, str):
        return time.time()
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(val).timestamp()
    except Exception:
        return time.time()


def image_type(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def read_text_snippet(full_path, max_bytes=TEXT_PREVIEW_BYTES, max_lines=14):
    try:
        with open(full_path, "rb") as f:
            raw = f.read(max_bytes + 1)
        if b"\x00" in raw[:512]:
            return "", 0
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        lines = text.splitlines()
        clipped = "\n".join(lines[:max_lines])
        truncated = len(raw) > max_bytes or len(lines) > max_lines
        return clipped, (len(lines) if not truncated else max(len(lines), max_lines))
    except OSError:
        return "", 0


def read_text_full(full_path):
    try:
        st = os.stat(full_path)
        with open(full_path, "rb") as f:
            raw = f.read(TEXT_MODAL_MAX_BYTES + 1)
        truncated = len(raw) > TEXT_MODAL_MAX_BYTES
        text = raw[:TEXT_MODAL_MAX_BYTES].decode("utf-8", errors="replace")
        return text, truncated, st.st_size
    except OSError:
        return None, False, 0


def norm_dir(path):
    if not path or not isinstance(path, str):
        return None
    if path.startswith("file://"):
        parsed = urllib.parse.urlsplit(path)
        path = urllib.parse.unquote(parsed.path)
    p = os.path.abspath(os.path.expanduser(path.strip()))
    if os.path.isdir(p):
        return p
    return None


def unwrap_arg(val):
    """Unwrap JSON-encoded string values as stored in Antigravity transcript.jsonl."""
    if not isinstance(val, str):
        return ""
    s = val.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            decoded = json.loads(s)
            if isinstance(decoded, str):
                return decoded.strip()
        except Exception:
            pass
    return s


WRITE_TOOLS = {
    "write_file", "edit_file", "write_to_file", "replace_file_content",
    "multi_replace_file_content", "create_file", "save_file", "notebook_edit",
}
EXEC_TOOLS = {"run_command", "bash", "shell", "execute_command"}
READONLY_PREFIXES = ("read_", "view_", "list_", "grep", "find_", "search_", "get_", "ls", "manage_", "ask_")
PATH_ARG_KEYS = (
    "Path", "path", "TargetFile", "target_file", "file_path",
    "output_path", "output", "out", "out_dir", "dest", "destination",
    "save_path", "save_dir", "filename", "directory", "dir",
)
CMD_OUTPUT_RE = re.compile(
    r"""(?:>>?|tee\s+(?:-a\s+)?|(?:-o|--out(?:put)?|--out-?dir|--save(?:-dir|-path)?|--dest(?:ination)?|--dir)\s*=?\s*|mkdir\s+(?:-p\s+)?)(["']?)([/~.][^"'\s;|&<>()]+)\1"""
)
ABS_PATH_RE = re.compile(r"""(?<![\w.-])(/(?:[\w.@+-]+/)+[\w.@+-]+)""")


def find_git_root(dir_path):
    cur = os.path.abspath(dir_path)
    home = os.path.abspath(os.path.expanduser("~"))
    stop = {"/", home, "/tmp", "/var", "/home"}
    while cur and cur not in stop:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def is_blocked_watch_dir(dir_path, brain_dir=None):
    d = os.path.abspath(os.path.expanduser(dir_path))
    home = os.path.abspath(os.path.expanduser("~"))
    blocked_exact = {
        "/", "/tmp", "/var", "/var/tmp", "/etc", "/usr", "/bin", "/sbin",
        "/lib", "/lib64", "/opt", "/proc", "/sys", "/dev", "/run", "/home",
        home,
        os.path.join(home, ".gemini"),
        os.path.join(home, ".gemini", "antigravity"),
        os.path.join(home, ".gemini", "config"),
        os.path.join(home, ".cache"),
        os.path.join(home, ".config"),
        os.path.join(home, ".local"),
    }
    if d in blocked_exact:
        return True
    blocked_prefixes = [
        "/proc", "/sys", "/dev", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/run",
        os.path.join(home, ".gemini", "antigravity", "builtin"),
        os.path.join(home, ".gemini", "config"),
        os.path.join(home, ".cache"),
    ]
    if brain_dir:
        blocked_prefixes.append(os.path.abspath(os.path.expanduser(brain_dir)))
    for pref in blocked_prefixes:
        try:
            if os.path.commonpath([d, pref]) == pref:
                return True
        except ValueError:
            pass
    if os.path.basename(d) in SKIP_DIRS:
        return True
    return False


def resolve_auto_watch_dir(path, brain_dir=None):
    raw = unwrap_arg(path)
    if not raw:
        return None
    if raw.startswith("file://"):
        raw = urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    p = os.path.abspath(os.path.expanduser(raw))
    d = p if os.path.isdir(p) else os.path.dirname(p)
    if not os.path.isdir(d):
        parent = os.path.dirname(d)
        if os.path.isdir(parent):
            d = parent
        else:
            return None
    if is_blocked_watch_dir(d, brain_dir=brain_dir):
        return None
    return d


def extract_written_paths(tool_name, args, cwd=""):
    """Return candidate file/directory paths written by an agent tool call."""
    if not isinstance(args, dict):
        return []
    tname = (tool_name or "").lower()
    out = []
    seen = set()

    def add_cand(p):
        p = unwrap_arg(p)
        if not p:
            return
        if p.startswith("file://"):
            p = urllib.parse.unquote(urllib.parse.urlsplit(p).path)
        if p.startswith("~"):
            p = os.path.expanduser(p)
        elif not os.path.isabs(p):
            if cwd and os.path.isabs(cwd):
                p = os.path.join(cwd, p)
            else:
                return
        p = os.path.abspath(p)
        if p not in seen:
            seen.add(p)
            out.append(p)

    if tname in WRITE_TOOLS:
        for k in PATH_ARG_KEYS:
            if k in args:
                add_cand(args[k])
        return out

    if tname in EXEC_TOOLS:
        cmd_cwd = unwrap_arg(args.get("Cwd") or args.get("cwd") or "") or cwd
        cmd = unwrap_arg(args.get("CommandLine") or args.get("command") or "")
        if cmd:
            for m in CMD_OUTPUT_RE.finditer(cmd):
                tok = m.group(2).rstrip(".,;:")
                if tok.startswith(("/", "~", "./", "../")):
                    add_cand(tok)
            now = time.time()
            for m in ABS_PATH_RE.finditer(cmd):
                cand = m.group(1).rstrip(".,;:")
                if cand in seen:
                    continue
                if os.path.isfile(cand):
                    if kind_of(cand)[0] is not None:
                        try:
                            if now - os.stat(cand).st_mtime < 600:
                                add_cand(cand)
                        except OSError:
                            pass
                elif os.path.isdir(cand):
                    try:
                        if now - os.stat(cand).st_mtime < 600:
                            add_cand(cand)
                    except OSError:
                        pass
        return out

    if not tname.startswith(READONLY_PREFIXES):
        for k in PATH_ARG_KEYS:
            if k in args:
                add_cand(args[k])
    return out


def complete_dirs(prefix):
    if not prefix:
        base = os.path.expanduser("~")
        return [base] if os.path.isdir(base) else []
    expanded = os.path.expanduser(prefix)
    if os.path.isdir(expanded) and expanded.endswith(os.sep):
        parent, needle = expanded, ""
    else:
        parent, needle = os.path.dirname(expanded) or "/", os.path.basename(expanded)
    out = []
    try:
        with os.scandir(parent) as it:
            for e in it:
                if not e.name.startswith(".") or needle.startswith("."):
                    if e.name.lower().startswith(needle.lower()) and e.is_dir(follow_symlinks=False):
                        out.append(e.path)
                        if len(out) >= 24:
                            break
    except OSError:
        pass
    out.sort()
    return out


class Inotify:
    """Minimal Linux inotify via ctypes (no dependencies)."""
    CLOSE_WRITE, MOVED_FROM, MOVED_TO, CREATE, DELETE = 0x8, 0x40, 0x80, 0x100, 0x200
    MODIFY = 0x2
    Q_OVERFLOW, IGNORED, ISDIR = 0x4000, 0x8000, 0x40000000
    MASK = CLOSE_WRITE | MOVED_FROM | MOVED_TO | CREATE | DELETE | 0x01000000 | 0x02000000 | 0x04000000

    def __init__(self):
        self.libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self.fd = self.libc.inotify_init1(0x800 | 0x80000)  # NONBLOCK | CLOEXEC
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.wd_to_path = {}
        self.path_to_wd = {}

    def add(self, path, mask=None):
        if path in self.path_to_wd:
            return True
        b = os.fsencode(path)
        wd = self.libc.inotify_add_watch(self.fd, b, mask if mask is not None else self.MASK)
        if wd < 0:
            return False
        self.wd_to_path[wd] = path
        self.path_to_wd[path] = wd
        return True

    def remove(self, path):
        wd = self.path_to_wd.pop(path, None)
        if wd is not None:
            self.wd_to_path.pop(wd, None)
            try:
                self.libc.inotify_rm_watch(self.fd, wd)
            except Exception:
                pass

    def read_events(self, timeout=0.5):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        try:
            buf = os.read(self.fd, 65536)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return []
            raise
        events = []
        i, n = 0, len(buf)
        while i + 16 <= n:
            wd, mask, cookie, length = struct.unpack_from("iIII", buf, i)
            i += 16
            raw_name = buf[i:i + length].split(b"\x00", 1)[0]
            i += length
            name = os.fsdecode(raw_name) if raw_name else ""
            path = self.wd_to_path.get(wd)
            if mask & self.IGNORED:
                if path:
                    self.wd_to_path.pop(wd, None)
                    self.path_to_wd.pop(path, None)
                continue
            events.append((path, mask, name))
        return events

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class LiveStreamApp:
    """Unified multimodal stream combining workspace files, artifacts, transcripts, and hooks."""

    def __init__(self, initial_roots=None, brain_dir=None, exclude=None, use_poll=False, interval=1.0):
        self.lock = threading.RLock()
        self.exclude = set(SKIP_DIRS) | set(exclude or [])
        self.use_poll = use_poll or not sys.platform.startswith("linux")
        self.interval = max(0.3, float(interval))
        self.brain_dir = brain_dir
        self.roots = []  # watched workspace roots (abs paths)
        self.auto_roots = set()  # roots automatically discovered from agent writes
        self.root_projects = {}  # root_path -> set of project root paths that own/wrote to it
        self.ignored_roots = set()  # roots explicitly removed by user
        self.auto_follow_dirs = True
        self.scope_by_project = True
        self.recent_roots = []
        self.items = {}  # item_id -> dict
        self.file_index = {}  # realpath -> item_id (workspace/artifact/media files)
        self.attributions = {}  # realpath -> {convo, model, tool, ts}
        self.conversations = {}  # convo_id -> {id, title, last_ts, workspace, artifact_dir, transcript_path}
        self._transcript_offsets = {}  # transcript_path -> byte offset
        self._transcript_seen = set()  # (convo_id, step_index)
        self._watched_dirs = set()  # for inotify
        self._clients = set()
        self.version = 1
        self.last_event = {"v": 1, "id": "", "ev": ""}
        self._stop = threading.Event()
        self._dirty_event = threading.Event()
        self._pending_broadcast = {}  # item_id -> event_type
        self._inotify = None
        if not self.use_poll:
            try:
                self._inotify = Inotify()
            except Exception:
                self.use_poll = True

        self._load_state()
        if initial_roots:
            for r in initial_roots:
                self.add_root(r, persist=True, broadcast=False)

    def _load_state(self):
        try:
            with open(state_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if "auto_follow_dirs" in data:
                self.auto_follow_dirs = bool(data["auto_follow_dirs"])
            if "scope_by_project" in data:
                self.scope_by_project = bool(data["scope_by_project"])
            for r in data.get("roots", []):
                nd = norm_dir(r)
                if nd and nd not in self.roots:
                    self.roots.append(nd)
            for r in data.get("auto_roots", []):
                nd = norm_dir(r)
                if nd and nd in self.roots:
                    self.auto_roots.add(nd)
            for r, projs in (data.get("root_projects") or {}).items():
                nd = norm_dir(r)
                if nd and nd in self.roots and isinstance(projs, list):
                    self.root_projects[nd] = {
                        os.path.abspath(os.path.expanduser(p))
                        for p in projs if isinstance(p, str) and p.strip()
                    }
            for r in data.get("ignored_roots", []):
                if isinstance(r, str) and r.strip():
                    self.ignored_roots.add(os.path.abspath(os.path.expanduser(r.strip())))
            for r in data.get("recent", []):
                nd = norm_dir(r)
                if nd and nd not in self.recent_roots:
                    self.recent_roots.append(nd)
        except Exception:
            pass

    def _save_state(self):
        try:
            with open(state_file(), "w", encoding="utf-8") as f:
                json.dump({
                    "roots": self.roots,
                    "auto_roots": sorted(self.auto_roots),
                    "root_projects": {k: sorted(v) for k, v in self.root_projects.items() if v},
                    "ignored_roots": sorted(self.ignored_roots),
                    "auto_follow_dirs": self.auto_follow_dirs,
                    "scope_by_project": self.scope_by_project,
                    "recent": self.recent_roots[:20],
                }, f, indent=2)
        except OSError:
            pass

    def start(self):
        def _bootstrap():
            self._rescan_all_roots()
            if self.brain_dir and os.path.isdir(self.brain_dir):
                self._scan_brain(initial=True)
            self._send_all("refresh", {})

        threading.Thread(target=_bootstrap, daemon=True, name="bootstrap").start()
        threading.Thread(target=self._watch_loop, daemon=True, name="watcher").start()
        threading.Thread(target=self._brain_loop, daemon=True, name="brain-watcher").start()
        threading.Thread(target=self._flush_loop, daemon=True, name="sse-flusher").start()

    def stop(self):
        self._stop.set()
        self._dirty_event.set()
        if self._inotify:
            self._inotify.close()

    # ---------- Root management ----------

    def _is_ignored(self, nd):
        for ign in self.ignored_roots:
            try:
                if os.path.commonpath([nd, ign]) == ign:
                    return True
            except ValueError:
                pass
        return False

    def _tag_root_project(self, root_path, project):
        if not project:
            return
        proj = norm_dir(project)
        if not proj:
            return
        self.root_projects.setdefault(root_path, set()).add(proj)

    def add_root(self, path, persist=True, broadcast=True, auto=False, async_scan=False, project=None):
        nd = norm_dir(path)
        if not nd:
            return None
        proj_norm = norm_dir(project) if project else None
        with self.lock:
            if auto:
                if not self.auto_follow_dirs or self._is_ignored(nd):
                    return None
            else:
                self.ignored_roots.discard(nd)
                self.auto_roots.discard(nd)
            # Skip if already equal to or inside an existing root (still tag project ownership)
            for existing in self.roots:
                try:
                    if os.path.commonpath([nd, existing]) == existing:
                        if proj_norm:
                            self._tag_root_project(existing, proj_norm)
                            if persist:
                                self._save_state()
                        return existing
                except ValueError:
                    pass
            # Drop narrower roots covered by the new broader root (preserving their project tags)
            kept = []
            inherited_projects = set()
            for existing in self.roots:
                try:
                    if os.path.commonpath([nd, existing]) == nd and existing != nd:
                        self.auto_roots.discard(existing)
                        inherited_projects |= self.root_projects.pop(existing, set())
                        continue
                except ValueError:
                    pass
                kept.append(existing)
            kept.append(nd)
            self.roots = kept
            if auto:
                self.auto_roots.add(nd)
            if inherited_projects:
                self.root_projects.setdefault(nd, set()).update(inherited_projects)
            if proj_norm:
                self._tag_root_project(nd, proj_norm)
            if nd in self.recent_roots:
                self.recent_roots.remove(nd)
            self.recent_roots.insert(0, nd)
            if persist:
                self._save_state()

        if broadcast:
            self._send_all("roots", {"roots": self.roots_payload(), "recent": self.recent_roots})

        if async_scan:
            def _bg():
                self._scan_root(nd)
                if broadcast:
                    self._send_all("refresh", {})
            threading.Thread(target=_bg, daemon=True, name="root-scan").start()
        else:
            self._scan_root(nd)
            if broadcast:
                self._send_all("refresh", {})
        return nd

    def remove_root(self, path):
        nd = norm_dir(path) or os.path.abspath(os.path.expanduser(path))
        with self.lock:
            if nd not in self.roots:
                return False
            self.roots.remove(nd)
            self.auto_roots.discard(nd)
            self.root_projects.pop(nd, None)
            self.ignored_roots.add(nd)
            # Remove items belonging to this root
            drop_ids = [
                iid for iid, it in self.items.items()
                if it.get("source") == "workspace" and it.get("root") == nd
            ]
            for iid in drop_ids:
                it = self.items.pop(iid, None)
                if it and it.get("full_path"):
                    self.file_index.pop(it["full_path"], None)
            self._save_state()
        self._send_all("roots", {"roots": self.roots_payload(), "recent": self.recent_roots})
        self._send_all("refresh", {})
        return True

    def set_auto_follow(self, enabled):
        with self.lock:
            self.auto_follow_dirs = bool(enabled)
            self._save_state()
        self._send_all("roots", {
            "roots": self.roots_payload(),
            "recent": self.recent_roots,
            "auto_follow_dirs": self.auto_follow_dirs,
            "scope_by_project": self.scope_by_project,
        })
        return self.auto_follow_dirs

    def set_scope_by_project(self, enabled):
        with self.lock:
            self.scope_by_project = bool(enabled)
            self._save_state()
        self._send_all("roots", {
            "roots": self.roots_payload(),
            "recent": self.recent_roots,
            "auto_follow_dirs": self.auto_follow_dirs,
            "scope_by_project": self.scope_by_project,
        })
        return self.scope_by_project

    def auto_follow_path(self, path, convo_id="", model="", tool="", notify=True, async_scan=True, allow_new_root=True, project=None):
        """Auto-watch the folder an agent wrote to and index the written file immediately."""
        raw = unwrap_arg(path)
        if not raw:
            return None
        if raw.startswith("file://"):
            raw = urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
        full = os.path.abspath(os.path.expanduser(raw))
        rpath = os.path.realpath(full) if os.path.exists(full) else full
        if convo_id or model or tool:
            self.attributions[rpath] = {
                "convo": convo_id,
                "model": model,
                "tool": tool,
                "ts": time.time(),
            }

        # Infer conversation's project from its first git-repo write if not yet set
        eff_project = norm_dir(project) if project else None
        if not eff_project and convo_id:
            eff_project = self.conversations.get(convo_id, {}).get("project") or None
        if not eff_project:
            d = rpath if os.path.isdir(rpath) else os.path.dirname(rpath)
            if os.path.isdir(d):
                eff_project = find_git_root(d)
                if eff_project and convo_id and convo_id in self.conversations:
                    with self.lock:
                        if not self.conversations[convo_id].get("project"):
                            self.conversations[convo_id]["project"] = eff_project

        added_root = None
        if allow_new_root and self.auto_follow_dirs:
            watch_dir = resolve_auto_watch_dir(rpath, brain_dir=self.brain_dir)
            if watch_dir:
                added_root = self.add_root(
                    watch_dir,
                    persist=True,
                    broadcast=notify,
                    auto=True,
                    async_scan=async_scan,
                    project=eff_project,
                )

        if os.path.isfile(rpath) and kind_of(rpath)[0] is not None:
            source, root, owner_cid = self._find_owner_root(rpath)
            if source:
                rel = os.path.relpath(rpath, root)
                self._upsert_file(rpath, source, root, rel, convo_id=convo_id or owner_cid, notify=notify)
            else:
                # Written outside any watchable folder (e.g. directly in /tmp) — still stream the file!
                self._upsert_file(
                    rpath,
                    "output",
                    os.path.dirname(rpath),
                    os.path.basename(rpath),
                    convo_id=convo_id,
                    notify=notify,
                )
        return added_root

    def set_roots(self, paths):
        cleaned = []
        for p in paths:
            nd = norm_dir(p)
            if nd and nd not in cleaned:
                cleaned.append(nd)
        with self.lock:
            self.roots = cleaned
            for nd in cleaned:
                if nd in self.recent_roots:
                    self.recent_roots.remove(nd)
                self.recent_roots.insert(0, nd)
            # Drop workspace items no longer under any root
            drop_ids = [
                iid for iid, it in self.items.items()
                if it.get("source") == "workspace" and it.get("root") not in cleaned
            ]
            for iid in drop_ids:
                it = self.items.pop(iid, None)
                if it and it.get("full_path"):
                    self.file_index.pop(it["full_path"], None)
            self._save_state()
        self._rescan_all_roots()
        self._send_all("roots", {"roots": self.roots_payload(), "recent": self.recent_roots})
        self._send_all("refresh", {})
        return cleaned

    def roots_payload(self):
        with self.lock:
            return [
                {
                    "path": r,
                    "name": os.path.basename(r.rstrip("/")) or r,
                    "auto": r in self.auto_roots,
                }
                for r in self.roots
            ]

    # ---------- File scanning & item construction ----------

    def _should_skip_dir(self, name):
        if name in self.exclude:
            return True
        if name.startswith(".") and name not in (".agents", ".agent", ".github"):
            return True
        return False

    def _item_id(self, source, key):
        return hashlib.sha1(f"{source}:{key}".encode("utf-8")).hexdigest()[:16]

    def _thumb_key(self, full_path, mtime_ns, size):
        return hashlib.sha1(f"{full_path}:{mtime_ns}:{size}".encode("utf-8")).hexdigest()

    def _build_file_item(self, full_path, source, root_path, rel_path, convo_id=None):
        kind, ext = kind_of(full_path)
        if not kind:
            return None
        try:
            st = os.stat(full_path)
        except OSError:
            return None
        if not os.path.isfile(full_path):
            return None
        if st.st_size == 0 and kind in ("image", "model", "video", "audio"):
            return None

        rpath = os.path.realpath(full_path)
        iid = self._item_id(source, rpath)
        tkey = self._thumb_key(rpath, st.st_mtime_ns, st.st_size) if kind == "model" else ""
        has_thumb = bool(tkey and os.path.isfile(os.path.join(thumbs_dir(), tkey + ".webp")))
        # Snippets are loaded lazily in public_item() so scanning large trees opens zero files.
        snippet = None
        lines = 0

        attr = self.attributions.get(rpath) or {}
        cid = convo_id or attr.get("convo") or ""
        root_name = os.path.basename(root_path.rstrip("/")) or root_path
        if source == "artifact" and cid:
            root_name = f"artifact · {cid[:8]}"
        elif source == "media" and cid:
            root_name = f"media · {cid[:8]}"

        return {
            "id": iid,
            "kind": kind,
            "ext": ext.lstrip("."),
            "source": source,
            "root": root_path,
            "root_name": root_name,
            "rel": rel_path.replace(os.sep, "/"),
            "name": os.path.basename(full_path),
            "full_path": rpath,
            "mtime": st.st_mtime,
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
            "tkey": tkey,
            "has_thumb": has_thumb,
            "snippet": snippet,
            "lines": lines,
            "convo": cid,
            "model": attr.get("model", ""),
            "tool": attr.get("tool", ""),
        }

    def _upsert_file(self, full_path, source, root_path, rel_path, convo_id=None, notify=True, defer_prune=False):
        item = self._build_file_item(full_path, source, root_path, rel_path, convo_id=convo_id)
        if not item:
            return None
        with self.lock:
            existing = self.items.get(item["id"])
            if existing and existing.get("mtime_ns") == item["mtime_ns"] and existing.get("size") == item["size"]:
                # Update attribution even if file bytes didn't change
                if item["convo"] and not existing.get("convo"):
                    existing["convo"] = item["convo"]
                    existing["model"] = item["model"]
                    existing["tool"] = item["tool"]
                    if notify:
                        self._queue_event(item["id"], "update")
                return existing
            ev = "update" if existing else "add"
            self.items[item["id"]] = item
            self.file_index[item["full_path"]] = item["id"]
            if not defer_prune:
                self._prune_if_needed()
        if notify:
            self._queue_event(item["id"], ev)
        return item

    def _delete_file_path(self, full_path):
        rpath = os.path.realpath(full_path)
        with self.lock:
            iid = self.file_index.pop(rpath, None)
            if not iid:
                # Fallback match by stored full_path
                for k, v in list(self.items.items()):
                    if v.get("full_path") == full_path or v.get("full_path") == rpath:
                        iid = k
                        break
            if iid and iid in self.items:
                self.items.pop(iid, None)
                self._queue_event(iid, "delete")

    def _prune_if_needed(self):
        # Caller holds self.lock — prune file items and agent cards separately so
        # a folder with thousands of renders never evicts recent agent outputs.
        file_items = [x for x in self.items.values() if x["kind"] != "agent"]
        agent_items = [x for x in self.items.values() if x["kind"] == "agent"]
        if len(file_items) > MAX_WORKSPACE_ITEMS:
            file_items.sort(key=lambda x: x["mtime"], reverse=True)
            for it in file_items[MAX_WORKSPACE_ITEMS:]:
                self.items.pop(it["id"], None)
                if it.get("full_path"):
                    self.file_index.pop(it["full_path"], None)
        if len(agent_items) > MAX_AGENT_CARDS:
            agent_items.sort(key=lambda x: x["mtime"], reverse=True)
            for it in agent_items[MAX_AGENT_CARDS:]:
                self.items.pop(it["id"], None)

    def _watch_dir(self, dir_path):
        if self._inotify and dir_path not in self._watched_dirs:
            if self._inotify.add(dir_path):
                self._watched_dirs.add(dir_path)

    def _scan_root(self, root_path):
        if not os.path.isdir(root_path):
            return
        candidates = []
        dir_count = 0
        stack = [root_path]
        while stack and not self._stop.is_set():
            cur = stack.pop()
            dir_count += 1
            if dir_count > MAX_SCAN_DIRS_PER_ROOT:
                break
            self._watch_dir(cur)
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        name = e.name
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if not self._should_skip_dir(name):
                                    stack.append(e.path)
                                continue
                            if not e.is_file(follow_symlinks=False):
                                continue
                            kind, _ = kind_of(name)
                            if not kind:
                                continue
                            st = e.stat(follow_symlinks=False)
                            if st.st_size == 0 and kind in ("image", "model", "video", "audio"):
                                continue
                            candidates.append((st.st_mtime, e.path))
                        except OSError:
                            continue
            except OSError:
                continue

        # Only keep the newest MAX_PER_ROOT files from this root in memory
        top = heapq.nlargest(MAX_PER_ROOT, candidates, key=lambda x: x[0])
        for _, full in top:
            rel = os.path.relpath(full, root_path)
            self._upsert_file(full, "workspace", root_path, rel, notify=False, defer_prune=True)
        with self.lock:
            self._prune_if_needed()

    def _rescan_all_roots(self):
        with self.lock:
            roots = list(self.roots)
        for r in roots:
            self._scan_root(r)

    def _watch_loop(self):
        while not self._stop.is_set():
            if self._inotify and not self.use_poll:
                try:
                    events = self._inotify.read_events(timeout=0.5)
                except Exception:
                    events = []
                for dir_path, mask, name in events:
                    if not dir_path:
                        continue
                    if mask & Inotify.Q_OVERFLOW:
                        self._rescan_all_roots()
                        self._send_all("refresh", {})
                        continue
                    if not name:
                        continue
                    full = os.path.join(dir_path, name)
                    if mask & Inotify.ISDIR:
                        if mask & (Inotify.CREATE | Inotify.MOVED_TO):
                            if not self._should_skip_dir(name):
                                self._scan_subtree_for_event(full)
                        continue
                    if mask & (Inotify.DELETE | Inotify.MOVED_FROM):
                        self._delete_file_path(full)
                    elif mask & (Inotify.CLOSE_WRITE | Inotify.MOVED_TO):
                        self._handle_file_change(full)
            else:
                self._poll_roots()
                self._stop.wait(self.interval)

    def _find_owner_root(self, full_path):
        with self.lock:
            roots = list(self.roots)
        for r in roots:
            try:
                if os.path.commonpath([full_path, r]) == r:
                    return "workspace", r, None
            except ValueError:
                pass
        if self.brain_dir:
            try:
                if os.path.commonpath([full_path, self.brain_dir]) == self.brain_dir:
                    rel = os.path.relpath(full_path, self.brain_dir)
                    cid = rel.split(os.sep, 1)[0]
                    return "artifact", os.path.join(self.brain_dir, cid), cid
            except ValueError:
                pass
        return None, None, None

    def _scan_subtree_for_event(self, sub_dir):
        source, root, cid = self._find_owner_root(sub_dir)
        if not source:
            return
        for dirpath, dirnames, filenames in os.walk(sub_dir):
            dirnames[:] = [d for d in dirnames if not self._should_skip_dir(d)]
            self._watch_dir(dirpath)
            for fname in filenames:
                kind, _ = kind_of(fname)
                if not kind:
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root)
                self._upsert_file(full, source, root, rel, convo_id=cid, notify=True)

    def _handle_file_change(self, full_path):
        kind, _ = kind_of(full_path)
        if not kind:
            return
        source, root, cid = self._find_owner_root(full_path)
        if not source:
            return
        rel = os.path.relpath(full_path, root)
        self._upsert_file(full_path, source, root, rel, convo_id=cid, notify=True)

    def _poll_roots(self):
        with self.lock:
            roots = list(self.roots)
        seen_paths = set()
        for r in roots:
            if not os.path.isdir(r):
                continue
            for dirpath, dirnames, filenames in os.walk(r):
                dirnames[:] = [d for d in dirnames if not self._should_skip_dir(d)]
                for fname in filenames:
                    kind, _ = kind_of(fname)
                    if not kind:
                        continue
                    full = os.path.join(dirpath, fname)
                    rpath = os.path.realpath(full)
                    seen_paths.add(rpath)
                    rel = os.path.relpath(full, r)
                    self._upsert_file(full, "workspace", r, rel, notify=True)
        with self.lock:
            stale = [
                it["full_path"] for it in self.items.values()
                if it.get("source") == "workspace" and it.get("full_path") not in seen_paths
            ]
        for p in stale:
            self._delete_file_path(p)

    # ---------- Antigravity brain & transcript watcher ----------

    def _brain_loop(self):
        while not self._stop.is_set():
            if self.brain_dir and os.path.isdir(self.brain_dir):
                try:
                    self._scan_brain(initial=False)
                except Exception:
                    pass
            self._stop.wait(1.0)

    def _scan_brain(self, initial=False):
        entries = []
        try:
            with os.scandir(self.brain_dir) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                        try:
                            mt = e.stat().st_mtime
                        except OSError:
                            mt = 0
                        # Prefer transcript mtime if present
                        tpath = os.path.join(e.path, ".system_generated", "logs", "transcript.jsonl")
                        if os.path.isfile(tpath):
                            try:
                                mt = max(mt, os.stat(tpath).st_mtime)
                            except OSError:
                                pass
                        entries.append((mt, e.name, e.path, tpath))
        except OSError:
            return

        entries.sort(reverse=True)
        now = time.time()
        init_auto_budget = [6]
        for mt, cid, cdir, tpath in entries[:MAX_BRAIN_CONVOS]:
            with self.lock:
                rec = self.conversations.setdefault(cid, {
                    "id": cid,
                    "last_ts": mt,
                    "artifact_dir": cdir,
                    "transcript_path": tpath,
                    "workspace": "",
                    "title": cid[:8],
                })
                rec["last_ts"] = max(rec["last_ts"], mt)
            self._scan_artifact_dir(cid, cdir, notify=not initial)
            if os.path.isfile(tpath):
                allow_auto = (not initial) or (now - mt < 6 * 3600 and init_auto_budget[0] > 0)
                before_roots = len(self.roots)
                self._tail_transcript(cid, tpath, notify=not initial, allow_auto_roots=allow_auto)
                if initial and len(self.roots) > before_roots:
                    init_auto_budget[0] = max(0, init_auto_budget[0] - (len(self.roots) - before_roots))

    def _scan_artifact_dir(self, cid, cdir, notify=True):
        if not os.path.isdir(cdir):
            return
        for dirpath, dirnames, filenames in os.walk(cdir):
            dirnames[:] = [d for d in dirnames if not self._should_skip_dir(d)]
            self._watch_dir(dirpath)
            for fname in filenames:
                if fname.startswith(".") or fname.endswith(".metadata.json"):
                    continue
                kind, _ = kind_of(fname)
                if not kind:
                    continue
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, cdir)
                self._upsert_file(full, "artifact", cdir, rel, convo_id=cid, notify=notify)

    def _tail_transcript(self, cid, tpath, notify=True, allow_auto_roots=True):
        try:
            st = os.stat(tpath)
        except OSError:
            return
        offset = self._transcript_offsets.get(tpath, 0)
        if st.st_size < offset:
            offset = 0
        if st.st_size == offset:
            return
        try:
            with open(tpath, "rb") as f:
                f.seek(offset)
                chunk = f.read()
        except OSError:
            return

        # Keep partial trailing line for next read
        last_nl = chunk.rfind(b"\n")
        if last_nl == -1:
            return
        complete = chunk[:last_nl + 1]
        self._transcript_offsets[tpath] = offset + len(complete)

        for raw_line in complete.splitlines():
            if not raw_line.strip():
                continue
            try:
                step = json.loads(raw_line.decode("utf-8", errors="replace"))
            except Exception:
                continue
            self._ingest_transcript_step(cid, step, notify=notify, allow_auto_roots=allow_auto_roots)

    def _ingest_transcript_step(self, cid, step, notify=True, allow_auto_roots=True):
        step_idx = step.get("step_index")
        key = (cid, step_idx)
        if step_idx is not None and key in self._transcript_seen:
            return
        if step_idx is not None:
            self._transcript_seen.add(key)

        stype = step.get("type", "")
        ts = parse_iso_ts(step.get("created_at"))
        model = step.get("model", "")

        # Extract short title from first user input
        if stype == "USER_INPUT" and step.get("content"):
            text = re.sub(r"</?USER_REQUEST>", "", step["content"]).strip()
            first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
            if first_line:
                with self.lock:
                    if cid in self.conversations and self.conversations[cid]["title"] == cid[:8]:
                        self.conversations[cid]["title"] = first_line[:60]

        # Extract tool call written paths & auto-follow their folders
        convo_rec = self.conversations.get(cid, {})
        convo_ws = convo_rec.get("workspace", "")
        convo_proj = convo_rec.get("project", "")
        for tc in step.get("tool_calls") or []:
            tname = tc.get("name", "")
            args = tc.get("args") or {}
            for written in extract_written_paths(tname, args, cwd=convo_ws):
                self.auto_follow_path(
                    written,
                    convo_id=cid,
                    model=model,
                    tool=tname,
                    notify=notify,
                    async_scan=True,
                    allow_new_root=allow_auto_roots,
                    project=convo_proj,
                )
                if not convo_proj:
                    convo_proj = self.conversations.get(cid, {}).get("project", "")

        # Extract media attachments
        for m in step.get("media") or []:
            uri = m.get("uri") or ""
            mpath = uri[7:] if uri.startswith("file://") else uri
            if mpath and os.path.isfile(mpath):
                self._upsert_file(
                    mpath,
                    "media",
                    os.path.dirname(mpath),
                    os.path.basename(mpath),
                    convo_id=cid,
                    notify=notify,
                )
                if allow_auto_roots:
                    watch_dir = resolve_auto_watch_dir(mpath, brain_dir=self.brain_dir)
                    if watch_dir:
                        self.add_root(
                            watch_dir,
                            persist=True,
                            broadcast=notify,
                            auto=True,
                            async_scan=True,
                            project=convo_proj or None,
                        )

        # Extract assistant output text/markdown/code responses
        if stype == "PLANNER_RESPONSE":
            content = (step.get("content") or "").strip()
            if content:
                iid = self._item_id("agent", f"{cid}:{step_idx}")
                lines = content.splitlines()
                first = next((l.strip("#* `>-") for l in lines if l.strip()), "Agent response")
                snippet = "\n".join(lines[:14])[:TEXT_PREVIEW_BYTES]
                with self.lock:
                    convo_title = self.conversations.get(cid, {}).get("title", cid[:8])
                    item = {
                        "id": iid,
                        "kind": "agent",
                        "ext": "md",
                        "source": "agent",
                        "root": cid,
                        "root_name": f"agent · {cid[:8]}",
                        "rel": convo_title,
                        "name": first[:72] or "Agent response",
                        "full_path": "",
                        "full_text": content,
                        "mtime": ts,
                        "mtime_ns": int(ts * 1e9),
                        "size": len(content.encode("utf-8")),
                        "tkey": "",
                        "has_thumb": False,
                        "snippet": snippet,
                        "lines": len(lines),
                        "convo": cid,
                        "model": model,
                        "tool": "",
                    }
                    self.items[iid] = item
                    self._prune_if_needed()
                if notify:
                    self._queue_event(iid, "add")

    # ---------- Hook ingestion ----------

    def ingest_hook(self, payload):
        cid = payload.get("conversationId") or ""
        model = payload.get("modelName") or ""
        workspaces = payload.get("workspacePaths") or []
        cwd = payload.get("cwd") or ""
        artifact_dir = payload.get("artifactDirectoryPath") or ""
        transcript_path = payload.get("transcriptPath") or ""
        tc = payload.get("toolCall") or {}
        tname = tc.get("name") or ""
        args = tc.get("args") or {}

        proj = None
        for wp in workspaces or ([cwd] if cwd else []):
            nd = norm_dir(wp)
            if nd and not is_blocked_watch_dir(nd, brain_dir=self.brain_dir):
                if not proj:
                    proj = nd
                self.add_root(nd, persist=True, broadcast=True, auto=True, async_scan=True, project=proj)

        if cid:
            with self.lock:
                rec = self.conversations.setdefault(cid, {
                    "id": cid,
                    "last_ts": time.time(),
                    "artifact_dir": artifact_dir,
                    "transcript_path": transcript_path,
                    "workspace": workspaces[0] if workspaces else cwd,
                    "project": proj or "",
                    "title": cid[:8],
                })
                rec["last_ts"] = time.time()
                if proj:
                    rec["project"] = proj
                if artifact_dir:
                    rec["artifact_dir"] = artifact_dir
                if transcript_path:
                    rec["transcript_path"] = transcript_path

        if artifact_dir and os.path.isdir(artifact_dir):
            self._scan_artifact_dir(cid, artifact_dir, notify=True)
        if transcript_path and os.path.isfile(transcript_path):
            self._tail_transcript(cid, transcript_path, notify=True, allow_auto_roots=True)

        base_cwd = cwd or (workspaces[0] if workspaces else "")
        for written in extract_written_paths(tname, args, cwd=base_cwd):
            self.auto_follow_path(
                written,
                convo_id=cid,
                model=model,
                tool=tname,
                notify=True,
                async_scan=True,
                allow_new_root=True,
                project=proj,
            )

        return {"ok": True}

    # ---------- Queries & thumbnails ----------

    def public_item(self, it):
        if it.get("snippet") is None:
            if it["kind"] in ("code", "text") and it.get("ext") != "pdf" and it.get("full_path"):
                snip, lines = read_text_snippet(it["full_path"])
                it["snippet"] = snip
                it["lines"] = lines
            else:
                it["snippet"] = ""
        return {k: v for k, v in it.items() if k not in ("full_text", "mtime_ns")}

    def _is_under(self, path, parent):
        if not path or not parent:
            return False
        try:
            return os.path.commonpath([os.path.abspath(path), os.path.abspath(parent)]) == os.path.abspath(parent)
        except ValueError:
            return False

    def listing(self, q):
        kind = q.get("kind", "all")
        root = q.get("root", "")
        convo = q.get("convo", "")
        active_convo = q.get("active_convo", "")
        req_project = norm_dir(q.get("project", "")) or ""
        scope_param = q.get("scope", "")
        needle = (q.get("q") or "").strip().lower()
        try:
            offset = max(0, int(q.get("offset", 0)))
        except ValueError:
            offset = 0
        try:
            limit = max(1, min(200, int(q.get("limit", 60))))
        except ValueError:
            limit = 60

        with self.lock:
            all_items = list(self.items.values())
            all_roots = self.roots_payload()
            root_projects_snap = {k: set(v) for k, v in self.root_projects.items()}
            recent = list(self.recent_roots)
            convo_map = {cid: dict(c) for cid, c in self.conversations.items()}
            convos = sorted(convo_map.values(), key=lambda c: c["last_ts"], reverse=True)[:12]
            scope_by_project = self.scope_by_project

        # Resolve active project from workspace URI or active conversation
        resolved_project = req_project
        if not resolved_project and active_convo:
            resolved_project = norm_dir(convo_map.get(active_convo, {}).get("project", "")) or ""

        # Determine whether to apply per-project filtering
        use_project_scope = (
            (scope_param == "project")
            or (scope_param == "" and scope_by_project)
        ) and bool(resolved_project or active_convo)

        matching_root_paths = set()
        if use_project_scope:
            for r in all_roots:
                rp = r["path"]
                if resolved_project and (
                    self._is_under(rp, resolved_project)
                    or resolved_project in root_projects_snap.get(rp, set())
                ):
                    matching_root_paths.add(rp)
            roots = [r for r in all_roots if r["path"] in matching_root_paths]
        else:
            roots = all_roots

        counts = {
            "all": 0, "media": 0, "model": 0, "image": 0,
            "video": 0, "audio": 0, "code": 0, "text": 0, "agent": 0,
        }
        filtered = []
        for it in all_items:
            if use_project_scope:
                it_convo = it.get("convo") or ""
                it_convo_proj = convo_map.get(it_convo, {}).get("project", "") if it_convo else ""
                it_root = it.get("root") or ""
                it_path = it.get("full_path") or ""
                matches = False
                if active_convo and it_convo == active_convo:
                    matches = True
                elif resolved_project:
                    if it.get("source") == "workspace":
                        matches = (it_root in matching_root_paths) or self._is_under(it_path, resolved_project)
                    else:
                        matches = (
                            it_convo_proj == resolved_project
                            or self._is_under(it_path, resolved_project)
                            or (it_root in matching_root_paths)
                        )
                if not matches:
                    continue
            if root and it.get("root") != root:
                continue
            if convo and it.get("convo") != convo:
                continue
            if needle:
                hay = f"{it['name']} {it['rel']} {it['root_name']} {it.get('snippet') or ''}".lower()
                if needle not in hay:
                    continue
            k = it["kind"]
            counts["all"] += 1
            if k in counts:
                counts[k] += 1
            if k in ("model", "image", "video", "audio"):
                counts["media"] += 1

            if kind == "all":
                filtered.append(it)
            elif kind == "media" and k in ("model", "image", "video", "audio"):
                filtered.append(it)
            elif kind == k:
                filtered.append(it)

        filtered.sort(key=lambda x: x["mtime"], reverse=True)
        page = [self.public_item(x) for x in filtered[offset:offset + limit]]
        return {
            "items": page,
            "total": len(filtered),
            "more": offset + limit < len(filtered),
            "counts": counts,
            "roots": roots,
            "recent": recent,
            "auto_follow_dirs": self.auto_follow_dirs,
            "scope_by_project": scope_by_project,
            "resolved_project": resolved_project,
            "resolved_project_name": os.path.basename(resolved_project.rstrip("/")) if resolved_project else "",
            "conversations": [
                {"id": c["id"], "title": c["title"], "last_ts": c["last_ts"], "project": c.get("project", "")}
                for c in convos
            ],
        }

    def get_item(self, iid):
        with self.lock:
            return self.items.get(iid)

    def save_thumb(self, iid, tkey, body):
        if len(tkey) != 40 or any(c not in "0123456789abcdef" for c in tkey):
            return False
        path = os.path.join(thumbs_dir(), tkey + ".webp")
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
        except OSError:
            return False
        with self.lock:
            it = self.items.get(iid)
            if it and it.get("tkey") == tkey:
                it["has_thumb"] = True
        return True

    def send_reply(self, convo_id, message):
        message = (message or "").strip()
        if not message:
            return {"ok": False, "error": "empty message"}
        agentapi = shutil.which("agentapi")
        if not agentapi:
            return {"ok": False, "error": "agentapi not available in PATH (only available inside Antigravity sidecars)"}
        if not convo_id:
            # Pick most recent conversation
            with self.lock:
                convos = sorted(self.conversations.values(), key=lambda c: c["last_ts"], reverse=True)
                if convos:
                    convo_id = convos[0]["id"]
        if not convo_id:
            return {"ok": False, "error": "no active conversation selected"}
        try:
            proc = subprocess.run(
                [agentapi, "send-message", convo_id, message],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return {"ok": False, "error": (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()}
            return {"ok": True, "convo": convo_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------- SSE broadcast ----------

    def subscribe(self):
        q = queue.Queue(maxsize=256)
        with self.lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self._clients.discard(q)

    def _queue_event(self, iid, ev_type):
        with self.lock:
            prev = self._pending_broadcast.get(iid)
            if prev == "add" and ev_type == "update":
                pass
            else:
                self._pending_broadcast[iid] = ev_type
        self._dirty_event.set()

    def _flush_loop(self):
        while not self._stop.is_set():
            self._dirty_event.wait(0.25)
            self._dirty_event.clear()
            time.sleep(0.12)  # coalesce bursts
            with self.lock:
                if not self._pending_broadcast:
                    continue
                batch = dict(self._pending_broadcast)
                self._pending_broadcast.clear()
                if len(batch) > 25:
                    self._send_all("refresh", {"count": len(batch)})
                    continue
                payloads = []
                for iid, ev in batch.items():
                    if ev == "delete":
                        payloads.append(("delete", {"id": iid}))
                    else:
                        it = self.items.get(iid)
                        if it:
                            payloads.append((ev, self.public_item(it)))
            for ev, data in payloads:
                self._send_all(ev, data)

    def _send_all(self, event, data):
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
        with self.lock:
            self.version += 1
            self.last_event = {
                "v": self.version,
                "ev": event,
                "id": data.get("id", "") if isinstance(data, dict) else "",
            }
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.discard(q)


def make_handler(app, bound_port):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 15

        def log_message(self, *args):
            pass

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            path = u.path
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

            if path == "/healthz":
                return self.send_json({"ok": True, "port": bound_port})
            if path == "/api/version":
                with app.lock:
                    return self.send_json(dict(app.last_event))
            if path == "/" or path == "/index.html":
                return self.send_bytes(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/preload.js":
                return self.send_bytes(b"/* standalone preload stub */\n", "text/javascript; charset=utf-8")
            if path == "/kit.js":
                return self.send_bytes(KIT_JS.encode("utf-8"), "text/javascript; charset=utf-8")
            if path == "/worker.js":
                return self.send_bytes(WORKER_JS.encode("utf-8"), "text/javascript; charset=utf-8")
            if path == "/api/list":
                return self.send_json(app.listing(q))
            if path == "/api/dirs":
                return self.send_json({"dirs": complete_dirs(q.get("prefix", ""))})
            if path == "/api/text":
                return self.serve_text(q.get("id", ""))
            if path == "/events":
                return self.serve_events()
            if path.startswith("/f/"):
                return self.serve_file(path[3:], versioned="v" in q)
            if path.startswith("/t/"):
                return self.serve_thumb(path[3:])
            self.send_error(404)

        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            ctype = self.headers.get("Content-Type", "")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= THUMB_MAX:
                return self.send_error(413)
            body = self.rfile.read(n)

            if u.path == "/api/thumb":
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if not ctype.startswith("image/") or not image_type(body[:16]):
                    return self.send_json({"error": "expected image"}, 415)
                ok = app.save_thumb(q.get("id", ""), q.get("v", ""), body)
                return self.send_json({"ok": ok})

            if not ctype.startswith("application/json"):
                return self.send_json({"error": "expected JSON"}, 415)
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                return self.send_json({"error": "invalid JSON"}, 400)

            if u.path == "/api/hook":
                return self.send_json(app.ingest_hook(data))

            if u.path == "/api/watch":
                if "add" in data:
                    res = app.add_root(
                        data["add"],
                        async_scan=bool(data.get("async")),
                        project=data.get("project"),
                    )
                    if not res:
                        return self.send_json({"error": f"not a folder: {data['add']}"}, 400)
                    return self.send_json({"ok": True, "roots": app.roots_payload()})
                if "remove" in data:
                    app.remove_root(data["remove"])
                    return self.send_json({"ok": True, "roots": app.roots_payload()})
                if "roots" in data:
                    roots = data["roots"]
                    if isinstance(roots, str):
                        roots = [roots]
                    if not isinstance(roots, list):
                        return self.send_json({"error": "roots must be a list"}, 400)
                    app.set_roots(roots)
                    return self.send_json({"ok": True, "roots": app.roots_payload()})
                return self.send_json({"error": "missing add/remove/roots"}, 400)

            if u.path == "/api/settings":
                resp = {"ok": True}
                changed = False
                if "auto_follow_dirs" in data:
                    resp["auto_follow_dirs"] = app.set_auto_follow(bool(data["auto_follow_dirs"]))
                    changed = True
                if "scope_by_project" in data:
                    resp["scope_by_project"] = app.set_scope_by_project(bool(data["scope_by_project"]))
                    changed = True
                if changed:
                    return self.send_json(resp)
                return self.send_json({"error": "no valid settings"}, 400)

            if u.path == "/api/reply":
                res = app.send_reply(data.get("convo", ""), data.get("message", ""))
                return self.send_json(res, 200 if res.get("ok") else 400)

            self.send_error(404)

        def send_json(self, obj, status=200):
            return self.send_bytes(json.dumps(obj).encode("utf-8"), "application/json", status)

        def send_bytes(self, body, ctype, status=200, cache="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def serve_text(self, iid):
            it = app.get_item(iid)
            if not it:
                return self.send_json({"error": "not found"}, 404)
            if it["kind"] == "agent":
                return self.send_json({
                    "id": iid,
                    "name": it["name"],
                    "kind": "agent",
                    "text": it.get("full_text", it.get("snippet", "")),
                    "truncated": False,
                    "size": it.get("size", 0),
                    "convo": it.get("convo", ""),
                    "model": it.get("model", ""),
                })
            text, truncated, size = read_text_full(it["full_path"])
            if text is None:
                return self.send_json({"error": "unreadable"}, 404)
            return self.send_json({
                "id": iid,
                "name": it["name"],
                "rel": it["rel"],
                "full_path": it["full_path"],
                "kind": it["kind"],
                "ext": it["ext"],
                "text": text,
                "truncated": truncated,
                "size": size,
                "convo": it.get("convo", ""),
            })

        def serve_thumb(self, tkey):
            if len(tkey) != 40 or any(c not in "0123456789abcdef" for c in tkey):
                return self.send_error(404)
            try:
                with open(os.path.join(thumbs_dir(), tkey + ".webp"), "rb") as f:
                    body = f.read()
            except OSError:
                return self.send_error(404)
            self.send_bytes(body, image_type(body[:16]) or "image/webp", cache=IMMUTABLE)

        def serve_file(self, iid, versioned=False):
            # Support relative companion files for glTF (e.g. /f/<iid>/textures/albedo.png)
            base_id, _, extra = iid.partition("/")
            it = app.get_item(base_id)
            if not it or not it.get("full_path"):
                return self.send_error(404)
            full = it["full_path"]
            if extra:
                extra_dec = urllib.parse.unquote(extra)
                cand = os.path.realpath(os.path.join(os.path.dirname(full), extra_dec))
                root_real = os.path.realpath(it["root"])
                try:
                    if os.path.commonpath([cand, root_real]) != root_real:
                        return self.send_error(403)
                except ValueError:
                    return self.send_error(403)
                full = cand
            if not os.path.isfile(full):
                return self.send_error(404)

            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            try:
                size = os.path.getsize(full)
                f = open(full, "rb")
            except OSError:
                return self.send_error(404)

            with f:
                range_hdr = self.headers.get("Range")
                start, end = 0, size - 1
                status = 200
                if range_hdr and range_hdr.startswith("bytes=") and size > 0:
                    spec = range_hdr[6:].split(",", 1)[0].strip()
                    a, _, b = spec.partition("-")
                    try:
                        if a == "":
                            length = int(b)
                            start = max(0, size - length)
                        else:
                            start = int(a)
                            end = int(b) if b else size - 1
                        end = min(end, size - 1)
                        if 0 <= start <= end:
                            status = 206
                    except ValueError:
                        start, end, status = 0, size - 1, 200

                length = max(0, end - start + 1) if size > 0 else 0
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", IMMUTABLE if versioned else "no-cache")
                self.end_headers()
                f.seek(start)
                rem = length
                try:
                    while rem > 0:
                        chunk = f.read(min(1 << 20, rem))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        rem -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        def serve_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = app.subscribe()
            try:
                self.wfile.write(b"event: hello\ndata: {}\n\n")
                self.wfile.flush()
                while not app._stop.is_set():
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.unsubscribe(q)
                self.close_connection = True

    return H


KIT_JS = r"""// 3D helpers shared by the page and the thumbnail worker (Three.js from jsDelivr on first use).
const CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/';
const X = p => CDN + 'examples/jsm/' + p + '/+esm';
let T;
export async function three() {
  if (T) return T;
  const [THREE, { GLTFLoader }, { DRACOLoader }, { MeshoptDecoder }, { OBJLoader }, { STLLoader }, { PLYLoader }, { FBXLoader }, { RoomEnvironment }] = await Promise.all([
    import(CDN + '+esm'), import(X('loaders/GLTFLoader.js')), import(X('loaders/DRACOLoader.js')),
    import(X('libs/meshopt_decoder.module.js')), import(X('loaders/OBJLoader.js')), import(X('loaders/STLLoader.js')),
    import(X('loaders/PLYLoader.js')), import(X('loaders/FBXLoader.js')), import(X('environments/RoomEnvironment.js'))]);
  const draco = new DRACOLoader(); draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
  const gltf = new GLTFLoader(); gltf.setDRACOLoader(draco); gltf.setMeshoptDecoder(MeshoptDecoder);
  T = { THREE, RoomEnvironment, L: { gltf, glb: gltf, obj: new OBJLoader(), stl: new STLLoader(), ply: new PLYLoader(), fbx: new FBXLoader() } };
  return T;
}
export async function orbit() { return (await import(X('controls/OrbitControls.js'))).OrbitControls; }
export async function loadModel(url, ext, onProgress) {
  const obj = await readModel(url, ext, onProgress);
  obj.traverse(o => { for (const m of [].concat(o.material || [])) if ('envMapIntensity' in m) m.envMapIntensity = 0.45; });
  return obj;
}
async function readModel(url, ext, onProgress) {
  const { THREE, L } = await three();
  if (ext === 'glb' || ext === 'gltf') return (await L.gltf.loadAsync(url, onProgress)).scene;
  if (ext === 'obj' || ext === 'fbx') return await L[ext].loadAsync(url, onProgress);
  const geo = await L[ext].loadAsync(url, onProgress), colored = !!geo.attributes.color;
  if (ext === 'ply' && !geo.index) {
    geo.computeBoundingSphere();
    return new THREE.Points(geo, new THREE.PointsMaterial({ size: geo.boundingSphere.radius / 200, vertexColors: colored, color: colored ? 0xffffff : 0xb8c0cc }));
  }
  if (!geo.attributes.normal) geo.computeVertexNormals();
  return new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: colored ? 0xffffff : 0xb8c0cc, vertexColors: colored, roughness: .55, metalness: .1 }));
}
export function stage(renderer) {
  const { THREE, RoomEnvironment } = T, scene = new THREE.Scene(), pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture; pm.dispose();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 0.15));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(3, 5, 4); scene.add(d);
  return scene;
}
export function frame(cam, obj, ctl) {
  const { THREE } = T, box = new THREE.Box3().setFromObject(obj); if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2 || 1;
  const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2));
  cam.position.copy(c).addScaledVector(new THREE.Vector3(1, .7, 1.2).normalize(), dist * 1.02);
  cam.near = dist / 100; cam.far = dist * 100; cam.updateProjectionMatrix(); cam.lookAt(c);
  if (ctl) { ctl.target.copy(c); ctl.update(); }
}
export function dispose(obj) {
  obj.traverse(o => {
    o.geometry?.dispose();
    for (const m of [].concat(o.material || [])) { for (const k in m) if (m[k]?.isTexture) m[k].dispose(); m.dispose(); }
  });
}
export async function thumbKit(canvas, size) {
  const { THREE } = await three();
  const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  r.setSize(size, size, false);
  return { r, scene: stage(r), cam: new THREE.PerspectiveCamera(35, 1, .01, 1000) };
}
export async function drawThumb(kit, url, ext) {
  const obj = await loadModel(url, ext);
  try { kit.scene.add(obj); frame(kit.cam, obj); kit.r.render(kit.scene, kit.cam); }
  finally { kit.scene.remove(obj); dispose(obj); }
}
"""

WORKER_JS = r"""import { thumbKit, drawThumb } from './kit.js';
let kit = null;
self.onmessage = async e => {
  const { url, ext, size } = e.data;
  if (!kit) {
    try { kit = await thumbKit(new OffscreenCanvas(size, size), size); }
    catch (err) { postMessage({ error: String(err?.message || err), fatal: true }); return; }
  }
  try {
    await drawThumb(kit, url, ext);
    postMessage({ blob: await kit.r.domElement.convertToBlob({ type: 'image/webp', quality: 0.9 }) });
  } catch (err) {
    const error = String(err?.message || err);
    postMessage({ error, dom: /document|window|Image|createElement/.test(error) });
  }
};
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live Gallery</title>
<script src="/preload.js"></script>
<style>
:root{
  --bg:#0d1016; --panel:#131720; --card:#181d28; --card-hover:#1e2534;
  --line:#252c3b; --text:#e8ecf4; --muted:#8b95a9; --accent:#6aa9ff;
  --new:#4ade80; --upd:#fbbf24; --code-bg:#0f131b; --badge-bg:rgba(13,16,22,.78);
  --size:220px; color-scheme:dark;
}
:root[data-theme="light"]{
  --bg:#f5f7fb; --panel:#ffffff; --card:#ffffff; --card-hover:#f0f4fa;
  --line:#dce2ee; --text:#182030; --muted:#616d82; --accent:#2563eb;
  --new:#16a34a; --upd:#d97706; --code-bg:#f3f5fa; --badge-bg:rgba(255,255,255,.88);
  color-scheme:light;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;height:100%}
button,input,select{font:inherit;color:inherit}
header{position:sticky;top:0;z-index:20;background:var(--panel);border-bottom:1px solid var(--line);padding:8px 10px;display:flex;flex-direction:column;gap:7px}
.row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:6px;font-weight:600;letter-spacing:.01em;margin-right:4px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--new);box-shadow:0 0 8px var(--new)}
.dot.off{background:#ef4444;box-shadow:none}
.search{flex:1;min-width:120px;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:4px 8px;outline:none}
.search:focus{border-color:var(--accent)}
.btn{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:4px 8px;cursor:pointer;white-space:nowrap;font-size:12px}
.btn:hover{border-color:var(--accent)}
.btn.on{background:rgba(106,169,255,.16);border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;padding-bottom:1px}
.tabs::-webkit-scrollbar{display:none}
.tab{background:transparent;border:1px solid var(--line);border-radius:999px;padding:2px 9px;cursor:pointer;font-size:11.5px;color:var(--muted);white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.tab.on{background:var(--accent);border-color:var(--accent);color:#09111f;font-weight:600}
.tab .cnt{opacity:.75;font-variant-numeric:tabular-nums}
.roots-bar{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:4px;background:var(--bg);border:1px solid var(--line);border-radius:999px;padding:2px 8px;font-size:11px;color:var(--muted);cursor:pointer;max-width:220px}
.chip.on{border-color:var(--accent);color:var(--accent)}
.chip .adot{width:5px;height:5px;border-radius:50%;background:var(--new);flex:none}
.chip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip .x{opacity:.6;padding:0 2px}
.chip .x:hover{opacity:1;color:#f87171}
.add-box{display:none;gap:6px;align-items:center;position:relative}
.add-box.open{display:flex}
.add-box input{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:4px 8px;outline:none}
.ac{position:absolute;top:100%;left:0;right:68px;background:var(--panel);border:1px solid var(--line);border-radius:6px;margin-top:3px;max-height:180px;overflow:auto;z-index:30;display:none}
.ac.open{display:block}
.ac div{padding:5px 8px;cursor:pointer;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac div:hover{background:var(--card-hover)}
.banner{display:none;position:sticky;top:92px;z-index:15;margin:8px 10px 0;padding:6px 10px;border-radius:7px;background:rgba(106,169,255,.15);border:1px solid var(--accent);color:var(--text);font-size:12px;cursor:pointer;text-align:center}
.banner.show{display:block}

main{padding:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(var(--size),100%),1fr));gap:10px}
.empty{padding:48px 16px;text-align:center;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column;transition:border-color .15s,transform .12s}
.card:hover{border-color:var(--accent);background:var(--card-hover)}
.card.is-new{animation:pop .35s ease;border-color:var(--new)}
.card.is-upd{border-color:var(--upd)}
@keyframes pop{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:none}}
.thumb{position:relative;aspect-ratio:4/3;background:var(--code-bg);overflow:hidden;display:flex;align-items:center;justify-content:center}
.thumb.media{aspect-ratio:1/1;background:repeating-conic-gradient(rgba(128,128,128,.08) 0% 25%,transparent 0% 50%) 50%/16px 16px,var(--code-bg)}
.thumb img,.thumb video{width:100%;height:100%;object-fit:contain;display:block}
.thumb.contain img{object-fit:contain;padding:4px}
.thumb pre{margin:0;padding:8px 9px;width:100%;height:100%;overflow:hidden;font:11px/1.42 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--text);white-space:pre-wrap;word-break:break-word;opacity:.92;mask-image:linear-gradient(180deg,#000 72%,transparent)}
.thumb .agent-preview{padding:10px;width:100%;height:100%;overflow:hidden;font-size:12px;line-height:1.45;color:var(--text);mask-image:linear-gradient(180deg,#000 75%,transparent)}
.thumb .audio-box{padding:12px;width:100%;display:flex;flex-direction:column;align-items:center;gap:8px}
.thumb .audio-box audio{width:100%;height:32px}
.thumb .pdf-box{font-size:28px;opacity:.75;display:flex;flex-direction:column;align-items:center;gap:4px}
.thumb .pdf-box small{font-size:11px;color:var(--muted)}
.pill{position:absolute;top:6px;left:6px;background:var(--badge-bg);backdrop-filter:blur(6px);border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.pill.new{left:auto;right:6px;background:var(--new);color:#052e16;border-color:transparent}
.pill.upd{left:auto;right:6px;background:var(--upd);color:#451a03;border-color:transparent}
.meta{padding:7px 9px;display:flex;flex-direction:column;gap:2px;border-top:1px solid var(--line)}
.name{font-weight:600;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub{display:flex;justify-content:space-between;gap:6px;font-size:11px;color:var(--muted)}
.sub span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.attr{font-size:10.5px;color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Lightbox modal */
.modal{position:fixed;inset:0;z-index:50;background:rgba(6,8,12,.86);backdrop-filter:blur(8px);display:none;flex-direction:column}
.modal.open{display:flex}
.m-top{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
.m-title{flex:1;min-width:0}
.m-title strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.m-title small{display:block;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.m-body{flex:1;min-height:0;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden;touch-action:none}
.m-body.pz{cursor:grab}
.m-body.pz.grabbing{cursor:grabbing}
.m-body img{max-width:100%;max-height:100%;user-select:none;-webkit-user-drag:none;transform-origin:center;will-change:transform}
.m-body video{max-width:100%;max-height:100%;background:#000;transform-origin:center;will-change:transform}
.m-zoom{display:none;align-items:center;gap:4px}
.m-zoom.show{display:inline-flex}
.m-zoom .zpct{min-width:44px;text-align:center;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.m-body audio{width:min(520px,90%)}
.m-body canvas{width:100%!important;height:100%!important;display:block}
.m-body iframe{width:100%;height:100%;border:0;background:#fff}
.m-text{width:100%;height:100%;overflow:auto;padding:16px 20px;margin:0;background:var(--code-bg);color:var(--text);font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.m-text.prose{font:13.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;max-width:860px;margin:0 auto;width:100%}
.m-foot{display:flex;align-items:center;gap:6px;padding:8px 12px;background:var(--panel);border-top:1px solid var(--line)}
.m-foot input{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 9px;outline:none}
.m-foot input:focus{border-color:var(--accent)}
.status-msg{font-size:11.5px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="row">
    <div class="brand"><span class="dot" id="dot"></span>Live Gallery</div>
    <input class="search" id="search" placeholder="Filter path, text, code... (/)" autocomplete="off">
    <button class="btn on" id="btnScope" title="Filter to the current project (click to show all projects)">This project</button>
    <button class="btn on" id="btnAuto" title="Automatically watch folders that agents write to">Auto-watch</button>
    <button class="btn" id="btnFollow" title="Auto-open each new arrival">Follow</button>
    <button class="btn" id="btnPause" title="Hold incoming updates">Pause</button>
    <button class="btn" id="btnAdd" title="Add a folder to watch">+ Folder</button>
  </div>
  <div class="add-box" id="addBox">
    <input id="addInput" placeholder="/path/to/watch" autocomplete="off">
    <button class="btn on" id="addGo">Watch</button>
    <div class="ac" id="ac"></div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div class="roots-bar" id="rootsBar"></div>
</header>

<div class="banner" id="banner"></div>
<main>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none">No outputs yet. Watch a workspace folder or start an agent turn — new 3D models, images, videos, code, and agent outputs will stream in here automatically.</div>
</main>

<div class="modal" id="modal">
  <div class="m-top">
    <div class="m-title"><strong id="mName"></strong><small id="mSub"></small></div>
    <div class="m-zoom" id="mZoom">
      <button class="btn" id="zOut" title="Zoom out (-)">&minus;</button>
      <span class="zpct" id="zPct">Fit</span>
      <button class="btn" id="zIn" title="Zoom in (+)">+</button>
      <button class="btn" id="zOne" title="100% actual pixels (1)">1:1</button>
      <button class="btn" id="zFit" title="Fit to view (0)">Fit</button>
    </div>
    <button class="btn" id="mPrev" title="Previous (Left Arrow)">&larr;</button>
    <button class="btn" id="mNext" title="Next (Right Arrow)">&rarr;</button>
    <button class="btn" id="mCopy">Copy path</button>
    <button class="btn" id="mClose">Esc</button>
  </div>
  <div class="m-body" id="mBody"></div>
  <div class="m-foot">
    <input id="replyInput" placeholder="Send feedback about this item back to the agent...">
    <button class="btn on" id="replySend">Send to Agent</button>
    <span class="status-msg" id="replyStatus"></span>
  </div>
</div>

<script>
let kitMod = null;
async function getKit() {
  if (!kitMod) kitMod = await import('./kit.js');
  return kitMod;
}

function apiFetch(url, opts) {
  if (window.sidecar && typeof window.sidecar.fetch === 'function') {
    return window.sidecar.fetch(url, opts);
  }
  return fetch(url, opts);
}

const $ = s => document.querySelector(s);
const TABS = [
  ['all', 'All'], ['media', 'Media'], ['model', '3D'], ['image', 'Img'],
  ['video', 'Video'], ['audio', 'Audio'], ['code', 'Code'], ['text', 'Text'], ['agent', 'Agent']
];

let state = {
  kind: 'all', root: '', q: '',
  items: [], more: false, total: 0, counts: {}, roots: [], recent: [], convos: [],
  autoFollowDirs: true, scopeByProject: true,
  activeProject: '', activeProjectName: '',
  activeConvo: (window.sidecar && window.sidecar.conversationId) || new URLSearchParams(location.search).get('conversationId') || '',
  follow: false, paused: false, queued: 0, openIdx: -1,
};
let marks = new Map(); // id -> 'new' | 'upd'
let loading = false;
let viewerCleanup = null;
let sseConnected = false;

function uriToPath(u) {
  if (!u || typeof u !== 'string') return '';
  if (u.startsWith('file://')) {
    try { return decodeURIComponent(new URL(u).pathname); } catch {}
  }
  return u;
}

function updateScopeButton() {
  const btn = $('#btnScope');
  if (!btn) return;
  btn.classList.toggle('on', state.scopeByProject);
  if (state.scopeByProject) {
    btn.textContent = state.activeProjectName ? `Project: ${state.activeProjectName}` : 'This project';
    btn.title = 'Filtering to this project (including external folders its agents write to) — click to show all projects';
  } else {
    btn.textContent = 'All projects';
    btn.title = 'Showing all projects (remembered) — click to filter by current project';
  }
}

// --- Antigravity host bridge (theme + auto-discover open workspaces) ---
window.addEventListener('message', e => {
  const d = e.data;
  if (!d || typeof d !== 'object') return;
  const t = d.theme || d.colorTheme || (d.type === 'theme' ? d.value : null);
  if (typeof t === 'string') {
    document.documentElement.dataset.theme = /light/i.test(t) ? 'light' : 'dark';
  }
});

async function addHostUris(uris) {
  if (!Array.isArray(uris) || !uris.length) return;
  const primary = uriToPath(uris[0]);
  if (primary && primary !== state.activeProject) {
    state.activeProject = primary;
    state.activeProjectName = primary.replace(/\/+$/, '').split('/').pop() || primary;
    // Reset per-chip sub-filter when swapping to a different project
    state.root = '';
    updateScopeButton();
  }
  for (const u of uris) {
    try {
      await apiFetch('/api/watch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ add: u, project: primary || u, async: true }),
      });
    } catch {}
  }
}

async function syncHostWorkspaces() {
  try {
    if (window.sidecar && window.sidecar.conversationId) {
      state.activeConvo = window.sidecar.conversationId;
    }
    if (window.sidecar && typeof window.sidecar.getWorkspaceUris === 'function') {
      await addHostUris(await window.sidecar.getWorkspaceUris());
    }
    if (window.sidecar && typeof window.sidecar.onWorkspaceChange === 'function') {
      window.sidecar.onWorkspaceChange(uris => { addHostUris(uris).then(() => fetchList(true)); });
    }
  } catch {}
  updateScopeButton();
}

// --- 3D Thumbnail Worker (lazy via IntersectionObserver) ---
let worker = null, workerBusy = false, thumbQueue = [], fallbackKit = null;
const pending3D = new WeakMap();
const thumbObserver = typeof IntersectionObserver !== 'undefined'
  ? new IntersectionObserver(entries => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const job = pending3D.get(e.target);
        if (job) {
          pending3D.delete(e.target);
          thumbObserver.unobserve(e.target);
          enqueueThumb(job.item, job.imgEl);
        }
      }
    }, { rootMargin: '200px' })
  : null;

function observeThumb(cardEl, item, imgEl) {
  if (!thumbObserver) { enqueueThumb(item, imgEl); return; }
  pending3D.set(cardEl, { item, imgEl });
  thumbObserver.observe(cardEl);
}
function initWorker() {
  if (worker) return;
  try {
    worker = new Worker('./worker.js', { type: 'module' });
  } catch { worker = false; }
}

function enqueueThumb(item, imgEl) {
  thumbQueue.push({ item, imgEl });
  pumpThumbs();
}

async function pumpThumbs() {
  if (workerBusy || !thumbQueue.length) return;
  const job = thumbQueue.shift();
  if (!job.imgEl.isConnected) return pumpThumbs();
  workerBusy = true;
  const url = `/f/${job.item.id}?v=${job.item.mtime}`;
  try {
    let blob = null;
    initWorker();
    if (worker) {
      blob = await new Promise((resolve, reject) => {
        worker.onmessage = e => {
          if (e.data.error) reject(e.data);
          else resolve(e.data.blob);
        };
        worker.onerror = err => reject({ error: err.message, fatal: true });
        worker.postMessage({ url, ext: job.item.ext, size: 360 });
      }).catch(async err => {
        if (err && err.fatal) { worker.terminate(); worker = false; }
        if (err && (err.dom || err.fatal)) return await renderThumbMain(url, job.item.ext);
        throw err;
      });
    } else {
      blob = await renderThumbMain(url, job.item.ext);
    }
    if (blob) {
      const objUrl = URL.createObjectURL(blob);
      job.imgEl.src = objUrl;
      apiFetch(`/api/thumb?id=${encodeURIComponent(job.item.id)}&v=${encodeURIComponent(job.item.tkey)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'image/webp' },
        body: blob,
      }).catch(() => {});
    }
  } catch {}
  workerBusy = false;
  pumpThumbs();
}

async function renderThumbMain(url, ext) {
  const { thumbKit, drawThumb } = await getKit();
  if (!fallbackKit) {
    const c = document.createElement('canvas');
    c.width = 360; c.height = 360;
    fallbackKit = await thumbKit(c, 360);
  }
  await drawThumb(fallbackKit, url, ext);
  return await new Promise(res => fallbackKit.r.domElement.toBlob(res, 'image/webp', 0.9));
}

// --- Data loading ---
function relTime(sec) {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec));
  if (d < 5) return 'just now';
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

function fmtSize(n) {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function esc(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function fetchList(reset = true) {
  if (loading) return;
  loading = true;
  const offset = reset ? 0 : state.items.length;
  const qs = new URLSearchParams({
    kind: state.kind, root: state.root, q: state.q, offset: String(offset), limit: '24',
    project: state.activeProject, active_convo: state.activeConvo,
  });
  try {
    const r = await apiFetch('/api/list?' + qs.toString());
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.counts = data.counts || {};
    state.roots = data.roots || [];
    state.recent = data.recent || [];
    state.convos = data.conversations || [];
    if (typeof data.auto_follow_dirs === 'boolean') {
      state.autoFollowDirs = data.auto_follow_dirs;
      $('#btnAuto').classList.toggle('on', state.autoFollowDirs);
    }
    if (typeof data.scope_by_project === 'boolean') {
      state.scopeByProject = data.scope_by_project;
    }
    if (!state.activeProject && data.resolved_project) {
      state.activeProject = data.resolved_project;
    }
    if (data.resolved_project_name) {
      state.activeProjectName = data.resolved_project_name;
    }
    updateScopeButton();
    state.more = !!data.more;
    state.total = data.total || 0;
    state.items = reset ? data.items : state.items.concat(data.items);
    renderTabs();
    renderRoots();
    renderGrid(reset);
  } catch (err) {
    const empty = $('#empty');
    empty.style.display = 'block';
    empty.textContent = `Could not load Live Gallery stream (${err?.message || err}). Retrying...`;
  } finally {
    loading = false;
  }
}

function renderTabs() {
  const el = $('#tabs');
  el.innerHTML = TABS.map(([k, label]) => {
    const c = state.counts[k] ?? 0;
    return `<button class="tab ${state.kind === k ? 'on' : ''}" data-kind="${k}">${label}<span class="cnt">${c}</span></button>`;
  }).join('');
}

function renderRoots() {
  const el = $('#rootsBar');
  if (!state.roots.length) {
    el.innerHTML = '<span style="font-size:11px;color:var(--muted)">Watching Antigravity brain &amp; artifacts · agent-written folders are picked up automatically</span>';
    return;
  }
  el.innerHTML = state.roots.map(r => `
    <div class="chip ${state.root === r.path ? 'on' : ''}" data-root="${esc(r.path)}" title="${esc(r.path)}${r.auto ? ' (auto-followed from agent writes)' : ''}">
      ${r.auto ? '<span class="adot" title="Auto-followed"></span>' : ''}
      <span>${esc(r.name)}</span>
      <span class="x" data-rm="${esc(r.path)}">&times;</span>
    </div>
  `).join('');
}

function cardNode(it, idx) {
  const div = document.createElement('div');
  const mark = marks.get(it.id);
  div.className = 'card' + (mark === 'new' ? ' is-new' : mark === 'upd' ? ' is-upd' : '');
  div.dataset.idx = String(idx);
  const badge = mark === 'new' ? '<span class="pill new">NEW</span>'
    : mark === 'upd' ? '<span class="pill upd">UPD</span>' : '';
  const typeLabel = it.kind === 'model' ? `3D · ${it.ext}` : it.kind === 'agent' ? 'AGENT' : (it.ext || it.kind);

  let thumbHtml = '';
  const fUrl = `/f/${it.id}?v=${it.mtime}`;
  if (it.kind === 'image') {
    thumbHtml = `<img loading="lazy" decoding="async" src="${fUrl}" alt="${esc(it.name)}">`;
  } else if (it.kind === 'model') {
    const tSrc = it.has_thumb ? `/t/${it.tkey}` : '';
    thumbHtml = `<img class="m3d" loading="lazy" decoding="async" ${tSrc ? `src="${tSrc}"` : ''} alt="${esc(it.name)}">`;
  } else if (it.kind === 'video') {
    thumbHtml = `<video muted loop playsinline preload="none" data-src="${fUrl}"></video><div class="pdf-box" style="position:absolute;pointer-events:none"><div>&#9654;</div><small>${esc(it.ext.toUpperCase())}</small></div>`;
  } else if (it.kind === 'audio') {
    thumbHtml = `<div class="audio-box"><div>&#9835; ${esc(it.ext.toUpperCase())}</div><audio controls preload="none" src="${fUrl}"></audio></div>`;
  } else if (it.kind === 'text' && it.ext === 'pdf') {
    thumbHtml = `<div class="pdf-box"><div>PDF</div><small>${esc(fmtSize(it.size))}</small></div>`;
  } else if (it.kind === 'agent') {
    thumbHtml = `<div class="agent-preview">${esc(it.snippet)}</div>`;
  } else {
    thumbHtml = `<pre>${esc(it.snippet || '(empty)')}</pre>`;
  }

  const attrLine = it.convo
    ? `<div class="attr">${esc(it.model ? `${it.model} · ` : '')}${esc(it.tool ? `${it.tool} · ` : '')}${esc(it.convo.slice(0, 8))}</div>`
    : '';

  const isMedia = it.kind === 'image' || it.kind === 'model' || it.kind === 'video';
  div.innerHTML = `
    <div class="thumb ${isMedia ? 'media' : ''} ${it.kind === 'model' ? 'contain' : ''}">
      ${thumbHtml}
      <span class="pill">${esc(typeLabel)}</span>
      ${badge}
    </div>
    <div class="meta">
      <div class="name" title="${esc(it.rel || it.name)}">${esc(it.name)}</div>
      <div class="sub"><span title="${esc(it.rel)}">${esc(it.root_name)}</span><span>${esc(relTime(it.mtime))}</span></div>
      ${attrLine}
    </div>
  `;

  if (it.kind === 'model' && !it.has_thumb) {
    observeThumb(div, it, div.querySelector('img.m3d'));
  }
  if (it.kind === 'video') {
    const vid = div.querySelector('video');
    div.addEventListener('mouseenter', () => {
      if (!vid.src && vid.dataset.src) vid.src = vid.dataset.src;
      vid.play().catch(() => {});
    });
    div.addEventListener('mouseleave', () => {
      vid.pause();
      vid.removeAttribute('src');
      vid.load();
    });
  }
  div.addEventListener('click', e => {
    if (e.target.closest('audio')) return;
    openModal(idx);
  });
  return div;
}

function renderGrid(reset) {
  const grid = $('#grid');
  const empty = $('#empty');
  if (reset) grid.innerHTML = '';
  empty.style.display = state.items.length ? 'none' : 'block';
  const start = reset ? 0 : grid.children.length;
  const frag = document.createDocumentFragment();
  for (let i = start; i < state.items.length; i++) {
    frag.appendChild(cardNode(state.items[i], i));
  }
  grid.appendChild(frag);
}

// --- Lightbox viewer ---
let activeZoom = null;

function attachPanZoom(body, el, isVideo = false) {
  el.draggable = false;
  let scale = 1, tx = 0, ty = 0;
  let drag = null, moved = false;

  const updateReadout = () => {
    $('#zPct').textContent = Math.abs(scale - 1) < 0.01 && !tx && !ty ? 'Fit' : `${Math.round(scale * 100)}%`;
  };
  const apply = () => {
    el.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    updateReadout();
  };
  const resetFit = () => { scale = 1; tx = 0; ty = 0; apply(); };
  const setNative100 = () => {
    const nw = el.naturalWidth || el.videoWidth || 0;
    const baseW = el.clientWidth || 0;
    if (nw && baseW) {
      scale = Math.min(16, Math.max(0.25, nw / baseW));
    } else {
      scale = 2;
    }
    tx = 0; ty = 0;
    apply();
  };
  const zoomAt = (factor, clientX, clientY) => {
    const rect = body.getBoundingClientRect();
    const cx = clientX - (rect.left + rect.width / 2);
    const cy = clientY - (rect.top + rect.height / 2);
    const next = Math.min(16, Math.max(0.25, scale * factor));
    const ratio = next / scale;
    tx = cx - (cx - tx) * ratio;
    ty = cy - (cy - ty) * ratio;
    scale = next;
    apply();
  };

  body.classList.add('pz');
  $('#mZoom').classList.add('show');
  updateReadout();

  const onWheel = e => {
    e.preventDefault();
    const step = e.ctrlKey ? 1.08 : 1.18;
    zoomAt(e.deltaY < 0 ? step : 1 / step, e.clientX, e.clientY);
  };
  const onDown = e => {
    if (e.button !== 0) return;
    // Let clicks on the bottom native video controls bar pass through
    if (isVideo) {
      const vr = el.getBoundingClientRect();
      if (e.clientY > vr.bottom - 48) return;
    }
    e.preventDefault();
    drag = { id: e.pointerId, sx: e.clientX, sy: e.clientY, ox: tx, oy: ty };
    moved = false;
    body.classList.add('grabbing');
    try { body.setPointerCapture(e.pointerId); } catch {}
  };
  const onMove = e => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
    tx = drag.ox + dx;
    ty = drag.oy + dy;
    apply();
  };
  const onUp = e => {
    if (!drag || e.pointerId !== drag.id) return;
    const wasClickOnBackdrop = !moved && e.target === body;
    drag = null;
    body.classList.remove('grabbing');
    try { body.releasePointerCapture(e.pointerId); } catch {}
    if (wasClickOnBackdrop) closeModal();
  };
  const onDbl = e => {
    if (isVideo) return;
    e.preventDefault();
    if (Math.abs(scale - 1) < 0.05) setNative100();
    else resetFit();
  };

  body.addEventListener('wheel', onWheel, { passive: false });
  body.addEventListener('pointerdown', onDown);
  body.addEventListener('pointermove', onMove);
  body.addEventListener('pointerup', onUp);
  body.addEventListener('pointercancel', onUp);
  el.addEventListener('dblclick', onDbl);

  activeZoom = {
    zoomIn: () => { const r = body.getBoundingClientRect(); zoomAt(1.3, r.left + r.width / 2, r.top + r.height / 2); },
    zoomOut: () => { const r = body.getBoundingClientRect(); zoomAt(1 / 1.3, r.left + r.width / 2, r.top + r.height / 2); },
    fit: resetFit,
    oneToOne: setNative100,
  };

  return () => {
    activeZoom = null;
    $('#mZoom').classList.remove('show');
    body.classList.remove('pz', 'grabbing');
    body.removeEventListener('wheel', onWheel);
    body.removeEventListener('pointerdown', onDown);
    body.removeEventListener('pointermove', onMove);
    body.removeEventListener('pointerup', onUp);
    body.removeEventListener('pointercancel', onUp);
    el.removeEventListener('dblclick', onDbl);
  };
}

async function openModal(idx) {
  if (idx < 0 || idx >= state.items.length) return;
  closeViewerCleanup();
  state.openIdx = idx;
  const it = state.items[idx];
  $('#mName').textContent = it.name;
  $('#mSub').textContent = it.full_path || `${it.root_name} · ${it.rel}`;
  $('#mCopy').style.display = it.full_path ? '' : 'none';
  $('#replyStatus').textContent = '';
  const body = $('#mBody');
  body.innerHTML = '';
  $('#modal').classList.add('open');

  const fUrl = `/f/${it.id}?v=${it.mtime}`;
  if (it.kind === 'image') {
    const img = document.createElement('img');
    img.src = fUrl;
    body.appendChild(img);
    viewerCleanup = attachPanZoom(body, img, false);
  } else if (it.kind === 'video') {
    const v = document.createElement('video');
    v.src = fUrl; v.controls = true; v.autoplay = true;
    body.appendChild(v);
    const pzClean = attachPanZoom(body, v, true);
    viewerCleanup = () => { pzClean(); v.pause(); v.src = ''; };
  } else if (it.kind === 'audio') {
    const a = document.createElement('audio');
    a.src = fUrl; a.controls = true; a.autoplay = true;
    body.appendChild(a);
    viewerCleanup = () => { a.pause(); a.src = ''; };
  } else if (it.kind === 'model') {
    body.innerHTML = '<div style="color:var(--muted)">Loading 3D model...</div>';
    try {
      const { three, orbit, loadModel, stage, frame, dispose } = await getKit();
      const [{ THREE }, OrbitControls] = await Promise.all([three(), orbit()]);
      if (state.openIdx !== idx) return;
      body.innerHTML = '';
      const canvas = document.createElement('canvas');
      body.appendChild(canvas);
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      const scene = stage(renderer);
      const cam = new THREE.PerspectiveCamera(38, 1, 0.01, 1000);
      const ctl = new OrbitControls(cam, canvas);
      ctl.enableDamping = true;
      const obj = await loadModel(fUrl, it.ext);
      if (state.openIdx !== idx) { dispose(obj); renderer.dispose(); return; }
      scene.add(obj);
      const resize = () => {
        const w = body.clientWidth || 600, h = body.clientHeight || 400;
        renderer.setSize(w, h, false);
        cam.aspect = w / h; cam.updateProjectionMatrix();
      };
      resize();
      frame(cam, obj, ctl);
      let raf = 0;
      const tick = () => { raf = requestAnimationFrame(tick); ctl.update(); renderer.render(scene, cam); };
      tick();
      window.addEventListener('resize', resize);
      viewerCleanup = () => {
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        ctl.dispose(); dispose(obj); renderer.dispose();
      };
    } catch (err) {
      body.innerHTML = `<div style="color:#f87171">Failed to load 3D model: ${esc(err?.message || err)}</div>`;
    }
  } else if (it.kind === 'text' && it.ext === 'pdf') {
    const iframe = document.createElement('iframe');
    iframe.src = fUrl;
    body.appendChild(iframe);
  } else {
    const pre = document.createElement('pre');
    pre.className = 'm-text' + (it.kind === 'agent' ? ' prose' : '');
    pre.textContent = 'Loading...';
    body.appendChild(pre);
    try {
      const r = await apiFetch(`/api/text?id=${encodeURIComponent(it.id)}`);
      const data = await r.json();
      pre.textContent = data.text || '(empty)';
      if (data.truncated) pre.textContent += '\n\n--- [truncated at 256 KB] ---';
    } catch {
      pre.textContent = '(failed to load)';
    }
  }
}

function closeViewerCleanup() {
  if (viewerCleanup) { try { viewerCleanup(); } catch {} viewerCleanup = null; }
}

function closeModal() {
  closeViewerCleanup();
  $('#modal').classList.remove('open');
  state.openIdx = -1;
}

async function sendFeedback() {
  const input = $('#replyInput');
  const note = input.value.trim();
  if (!note) return;
  const it = state.items[state.openIdx];
  const ref = it ? (it.full_path ? `Regarding \`${it.rel}\` (${it.full_path}):\n` : `Regarding "${it.name}":\n`) : '';
  const prompt = ref + note;
  $('#replyStatus').textContent = 'Sending...';
  try {
    if (window.sidecar?.agent?.sendMessage) {
      await window.sidecar.agent.sendMessage(prompt);
      input.value = '';
      $('#replyStatus').textContent = 'Sent!';
      return;
    }
    const r = await apiFetch('/api/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ convo: it?.convo || '', message: prompt }),
    });
    const res = await r.json();
    if (res.ok) {
      input.value = '';
      $('#replyStatus').textContent = 'Sent!';
    } else {
      $('#replyStatus').textContent = res.error || 'Failed';
    }
  } catch (e) {
    $('#replyStatus').textContent = 'Failed to send';
  }
}

// --- Events & Controls ---
$('#tabs').addEventListener('click', e => {
  const btn = e.target.closest('.tab');
  if (!btn) return;
  state.kind = btn.dataset.kind;
  fetchList(true);
});

$('#rootsBar').addEventListener('click', async e => {
  const rm = e.target.closest('[data-rm]');
  if (rm) {
    e.stopPropagation();
    const p = rm.dataset.rm;
    if (state.root === p) state.root = '';
    await apiFetch('/api/watch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ remove: p }) });
    fetchList(true);
    return;
  }
  const chip = e.target.closest('.chip');
  if (!chip) return;
  state.root = state.root === chip.dataset.root ? '' : chip.dataset.root;
  fetchList(true);
});

let searchTimer = 0;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value; fetchList(true); }, 150);
});

$('#btnScope').addEventListener('click', async () => {
  state.scopeByProject = !state.scopeByProject;
  state.root = '';
  updateScopeButton();
  await apiFetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope_by_project: state.scopeByProject }),
  });
  fetchList(true);
});

$('#btnAuto').addEventListener('click', async () => {
  state.autoFollowDirs = !state.autoFollowDirs;
  $('#btnAuto').classList.toggle('on', state.autoFollowDirs);
  await apiFetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_follow_dirs: state.autoFollowDirs }),
  });
});

$('#btnFollow').addEventListener('click', () => {
  state.follow = !state.follow;
  $('#btnFollow').classList.toggle('on', state.follow);
});

$('#btnPause').addEventListener('click', () => {
  state.paused = !state.paused;
  $('#btnPause').classList.toggle('on', state.paused);
  if (!state.paused && state.queued) {
    state.queued = 0;
    $('#banner').classList.remove('show');
    fetchList(true);
  }
});

$('#btnAdd').addEventListener('click', () => {
  $('#addBox').classList.toggle('open');
  if ($('#addBox').classList.contains('open')) $('#addInput').focus();
});

async function submitAddFolder() {
  const val = $('#addInput').value.trim();
  if (!val) return;
  const r = await apiFetch('/api/watch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ add: val, project: state.activeProject || undefined }),
  });
  const d = await r.json();
  if (d.ok) {
    $('#addInput').value = '';
    $('#ac').classList.remove('open');
    $('#addBox').classList.remove('open');
    fetchList(true);
  } else {
    alert(d.error || 'Could not watch folder');
  }
}

$('#addGo').addEventListener('click', submitAddFolder);
$('#addInput').addEventListener('keydown', e => { if (e.key === 'Enter') submitAddFolder(); });
$('#addInput').addEventListener('input', async e => {
  const v = e.target.value.trim();
  if (!v) { $('#ac').classList.remove('open'); return; }
  const r = await apiFetch('/api/dirs?prefix=' + encodeURIComponent(v));
  const d = await r.json();
  const ac = $('#ac');
  if (!d.dirs || !d.dirs.length) { ac.classList.remove('open'); return; }
  ac.innerHTML = d.dirs.map(p => `<div data-p="${esc(p)}">${esc(p)}</div>`).join('');
  ac.classList.add('open');
});
$('#ac').addEventListener('click', e => {
  const d = e.target.closest('[data-p]');
  if (!d) return;
  $('#addInput').value = d.dataset.p;
  $('#ac').classList.remove('open');
  $('#addInput').focus();
});

$('#banner').addEventListener('click', () => {
  state.queued = 0;
  $('#banner').classList.remove('show');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  fetchList(true);
});

$('#mClose').addEventListener('click', closeModal);
$('#zIn').addEventListener('click', () => activeZoom?.zoomIn());
$('#zOut').addEventListener('click', () => activeZoom?.zoomOut());
$('#zOne').addEventListener('click', () => activeZoom?.oneToOne());
$('#zFit').addEventListener('click', () => activeZoom?.fit());
$('#mPrev').addEventListener('click', () => { if (state.openIdx > 0) openModal(state.openIdx - 1); });
$('#mNext').addEventListener('click', () => { if (state.openIdx + 1 < state.items.length) openModal(state.openIdx + 1); });
$('#mCopy').addEventListener('click', () => {
  const it = state.items[state.openIdx];
  if (it?.full_path) navigator.clipboard?.writeText(it.full_path);
});
$('#replySend').addEventListener('click', sendFeedback);
$('#replyInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendFeedback(); });

window.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  if (e.key === '/') { e.preventDefault(); $('#search').focus(); }
  else if (e.key === 'Escape' && state.openIdx >= 0) closeModal();
  else if (e.key === 'ArrowLeft' && state.openIdx > 0) openModal(state.openIdx - 1);
  else if (e.key === 'ArrowRight' && state.openIdx + 1 < state.items.length) openModal(state.openIdx + 1);
  else if (activeZoom && (e.key === '+' || e.key === '=')) { e.preventDefault(); activeZoom.zoomIn(); }
  else if (activeZoom && e.key === '-') { e.preventDefault(); activeZoom.zoomOut(); }
  else if (activeZoom && e.key === '0') { e.preventDefault(); activeZoom.fit(); }
  else if (activeZoom && e.key === '1') { e.preventDefault(); activeZoom.oneToOne(); }
});

window.addEventListener('scroll', () => {
  if (state.more && !loading && window.innerHeight + window.scrollY >= document.body.offsetHeight - 400) {
    fetchList(false);
  }
}, { passive: true });

// --- Live Update Loop (short-lived /api/version checks: zero persistent sockets!) ---
let lastVersion = 0;
let pollInFlight = false;

async function pollVersion() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const r = await apiFetch('/api/version');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const info = await r.json();
    $('#dot').classList.remove('off');
    if (lastVersion === 0) {
      lastVersion = info.v || 1;
      return;
    }
    if (info.v && info.v !== lastVersion) {
      lastVersion = info.v;
      if (info.id && (info.ev === 'add' || info.ev === 'update')) {
        marks.set(info.id, info.ev === 'add' ? 'new' : 'upd');
      }
      if (state.paused || window.scrollY > 220) {
        state.queued++;
        const b = $('#banner');
        b.textContent = `${state.queued} new update${state.queued === 1 ? '' : 's'} — click to refresh`;
        b.classList.add('show');
        return;
      }
      await fetchList(true);
      if (state.follow && info.id && state.items.length && state.items[0].id === info.id) {
        openModal(0);
      }
    }
  } catch {
    $('#dot').classList.add('off');
  } finally {
    pollInFlight = false;
  }
}

(function boot() {
  fetchList(true);
  syncHostWorkspaces().then(() => fetchList(true));
  pollVersion();
  setInterval(pollVersion, 1200);
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Antigravity 2.0 Live Gallery sidecar server")
    ap.add_argument("dirs", nargs="*", help="extra folders to watch")
    ap.add_argument("-p", "--port", type=int, default=None, help="port to listen on")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--brain-dir", default=os.path.expanduser("~/.gemini/antigravity/brain"))
    ap.add_argument("--no-brain", action="store_true", help="disable Antigravity brain/transcript watching")
    ap.add_argument("-x", "--exclude", action="append", default=[])
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("-i", "--interval", type=float, default=1.0)
    args = ap.parse_args()

    env_port = os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT") or os.environ.get("PORT")
    desired_port = args.port or (int(env_port) if env_port and env_port.isdigit() else None)
    ports = [desired_port] if desired_port else list(range(8765, 8785))

    app = LiveStreamApp(
        initial_roots=args.dirs,
        brain_dir=None if args.no_brain else args.brain_dir,
        exclude=args.exclude,
        use_poll=args.poll,
        interval=args.interval,
    )

    srv = None
    bound_port = None
    for p in ports:
        try:
            srv = ThreadingHTTPServer((args.host, p), make_handler(app, p))
            bound_port = p
            break
        except OSError:
            continue
    if not srv:
        sys.exit(f"port unavailable: {desired_port or '8765-8784'}")

    write_runtime_info(bound_port)
    atexit.register(cleanup_runtime_info)
    app.start()

    sys.stdout.write(f"Live Gallery sidecar listening on http://{args.host}:{bound_port}/\n")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        srv.server_close()
        cleanup_runtime_info()


if __name__ == "__main__":
    main()
