#!/usr/bin/env python3
"""Lightweight Antigravity hook forwarder for Live Gallery.

Reads the lifecycle hook JSON payload from stdin and forwards it with a short
timeout to the running Live Gallery sidecar so active workspaces, artifact
directories, and file attributions appear immediately in the stream.

Always outputs `{}` and exits 0 so it never blocks or breaks an agent turn.
"""
import json
import os
import sys
import urllib.request


def runtime_paths():
    paths = []
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    paths.append(os.path.join(cache_home, "live-gallery", "sidecar-runtime.json"))
    data_dir = os.environ.get("PLUGIN_DATA")
    if data_dir:
        paths.append(os.path.join(data_dir, "sidecar-runtime.json"))
    return paths


def read_port():
    for path in runtime_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
            port = int(info.get("port") or 0)
            if 1 <= port <= 65535:
                return port
        except Exception:
            continue
    return None


def main():
    raw = sys.stdin.read()
    try:
        port = read_port()
        if port and raw.strip():
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/hook",
                data=raw.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.35):
                pass
    except Exception:
        pass
    sys.stdout.write("{}\n")


if __name__ == "__main__":
    main()
