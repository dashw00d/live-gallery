//! Paths, folder completion, thumbnail cache helpers. OWNED BY: app agent.
use std::path::PathBuf;

pub const SETTLE: f64 = 1.0; // seconds a file found mid-copy must stay unchanged before it is shown
pub const THUMB_MAX: usize = 3 << 20;

/// $XDG_CONFIG_HOME or ~/.config, + live-gallery/state.json
pub fn state_path() -> PathBuf {
    todo!()
}
/// $XDG_CACHE_HOME or ~/.cache, + live-gallery/thumbs
pub fn thumb_dir() -> PathBuf {
    todo!()
}
pub fn thumb_file(tkey: &str) -> PathBuf {
    let _ = tkey;
    todo!()
}
/// Sniff png/webp/jpeg from the first bytes, like Python image_type.
pub fn image_type(head: &[u8]) -> Option<&'static str> {
    let _ = head;
    todo!()
}
/// Keep the newest `keep` thumbnails once there are more than `limit` (defaults 6000/9000).
pub fn prune_thumbs(keep: usize, limit: usize) {
    let _ = (keep, limit);
    todo!()
}
/// Returns (roots, bad): expanded ~, absolute, existing dirs, deduped, nested ones dropped.
pub fn norm_roots(paths: &[String]) -> (Vec<String>, Vec<String>) {
    let _ = paths;
    todo!()
}
/// Folder autocomplete for the "Add a folder…" box (absolute prefixes only, max `limit`, trailing '/').
pub fn complete_dirs(prefix: &str, limit: usize) -> Vec<String> {
    let _ = (prefix, limit);
    todo!()
}
