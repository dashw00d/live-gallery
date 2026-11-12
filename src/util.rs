//! Paths, folder completion, thumbnail cache helpers.
use std::path::{Component, Path, PathBuf};
pub const SETTLE: f64 = 1.0;
pub const THUMB_MAX: usize = 3 << 20;
fn home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
}
fn expand(p: &str) -> PathBuf {
    if p == "~" {
        home()
    } else if let Some(rest) = p.strip_prefix("~/") {
        home().join(rest)
    } else {
        PathBuf::from(p)
    }
}
pub fn state_path() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home().join(".config"))
        .join("live-gallery/state.json")
}
pub fn thumb_dir() -> PathBuf {
    std::env::var_os("XDG_CACHE_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home().join(".cache"))
        .join("live-gallery/thumbs")
}
pub fn thumb_file(tkey: &str) -> PathBuf {
    thumb_dir().join(tkey)
}
pub fn image_type(head: &[u8]) -> Option<&'static str> {
    if head.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("image/png")
    } else if head.starts_with(b"RIFF") && head.get(8..12) == Some(b"WEBP") {
        Some("image/webp")
    } else if head.starts_with(b"\xff\xd8\xff") {
        Some("image/jpeg")
    } else {
        None
    }
}
pub fn prune_thumbs(keep: usize, limit: usize) {
    prune_in(&thumb_dir(), keep, limit);
}
fn prune_in(dir: &Path, keep: usize, limit: usize) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    let mut files: Vec<_> = entries
        .filter_map(Result::ok)
        .filter_map(|e| {
            let m = e.metadata().ok()?;
            if m.is_file() {
                Some((m.modified().ok()?, e.path()))
            } else {
                None
            }
        })
        .collect();
    if files.len() > limit {
        files.sort();
        for (_, p) in files.iter().take(files.len().saturating_sub(keep)) {
            let _ = std::fs::remove_file(p);
        }
    }
}
fn absolute(p: &Path) -> PathBuf {
    let p = if p.is_absolute() {
        p.to_path_buf()
    } else {
        std::env::current_dir().unwrap_or_default().join(p)
    };
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            _ => out.push(c.as_os_str()),
        }
    }
    out
}
pub fn norm_roots(paths: &[String]) -> (Vec<String>, Vec<String>) {
    let (mut roots, mut bad) = (Vec::new(), Vec::new());
    for p in paths {
        let p = p.trim();
        if p.is_empty() {
            continue;
        }
        let r = absolute(&expand(p));
        if !r.is_dir() {
            bad.push(p.to_string())
        } else {
            let r = r.to_string_lossy().into_owned();
            if !roots.contains(&r) {
                roots.push(r)
            }
        }
    }
    let filtered = roots
        .iter()
        .filter(|r| {
            !roots
                .iter()
                .any(|o| *r != o && Path::new(r.as_str()).starts_with(o))
        })
        .cloned()
        .collect();
    (filtered, bad)
}
pub fn complete_dirs(prefix: &str, limit: usize) -> Vec<String> {
    let raw = prefix.trim();
    let p = expand(raw);
    if !p.is_absolute() {
        return vec![];
    }
    let expanded = p.to_string_lossy();
    let (base, part) = if raw.ends_with('/') {
        (p.as_path(), "")
    } else {
        let (base, part) = expanded.rsplit_once('/').unwrap_or(("", ""));
        (Path::new(if base.is_empty() { "/" } else { base }), part)
    };
    let Ok(entries) = std::fs::read_dir(base) else {
        return vec![];
    };
    let mut entries: Vec<_> = entries.filter_map(Result::ok).collect();
    entries.sort_by_key(|e| e.file_name().to_string_lossy().to_lowercase());
    let mut out = Vec::new();
    for e in entries {
        let name = e.file_name().to_string_lossy().into_owned();
        if name.to_lowercase().starts_with(&part.to_lowercase())
            && (!name.starts_with('.') || part.starts_with('.'))
            && e.path().is_dir()
        {
            out.push(format!("{}/", e.path().display()));
            if out.len() >= limit {
                break;
            }
        }
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roots_and_completion() {
        let d = tempfile::tempdir().unwrap();
        std::fs::create_dir(d.path().join("Alpha")).unwrap();
        std::fs::create_dir(d.path().join(".hidden")).unwrap();
        let root = d.path().to_string_lossy().to_string();
        let (r, b) = norm_roots(&[
            format!("{root}/Alpha"),
            root.clone(),
            root.clone(),
            format!("{root}/missing"),
        ]);
        assert_eq!(r, vec![root.clone()]);
        assert_eq!(b.len(), 1);
        assert_eq!(
            complete_dirs(&format!("{root}/a"), 40),
            vec![format!("{root}/Alpha/")]
        );
        assert_eq!(
            complete_dirs(&format!("{root}/."), 40),
            vec![format!("{root}/.hidden/")]
        );
    }
    #[test]
    fn prune_cache() {
        let d = tempfile::tempdir().unwrap();
        for name in ["a", "b", "c"] {
            std::fs::write(d.path().join(name), name).unwrap();
        }
        prune_in(d.path(), 1, 2);
        assert_eq!(std::fs::read_dir(d.path()).unwrap().count(), 1);
    }
    #[test]
    fn sniff() {
        assert_eq!(image_type(b"\xff\xd8\xff"), Some("image/jpeg"));
        assert_eq!(image_type(b"no"), None);
    }
}
