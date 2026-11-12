//! Shared data types. OWNED BY: integrator. Change only by agreement (see PORTING.md).
use serde::Serialize;

pub const IMAGE_EXT: &[&str] = &[".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico"];
pub const MODEL_EXT: &[&str] = &[".glb", ".gltf", ".obj", ".stl", ".ply", ".fbx"];
/// Noise: dependencies, caches, browser/app profiles agents' tooling leaves behind.
pub const SKIP_DIRS: &[&str] = &[
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".tox", ".cache",
    "cache", "Cache", "site-packages", "vendor", "target", ".godot", ".import", "tool_profiles", "app_userdata",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Image,
    Model,
}

/// (root index, relative path with '/' separators)
pub type Key = (usize, String);

/// What a scan learns about one file. `ext` includes the dot and is lowercase (".png").
#[derive(Clone, Debug, PartialEq)]
pub struct FileInfo {
    pub size: u64,
    pub mtime: f64,
    pub kind: Kind,
    pub ext: String,
}

/// One gallery entry. Serializes to exactly the JSON the page expects (same fields as the Python version).
#[derive(Clone, Debug, Serialize)]
pub struct Item {
    pub id: String,     // "{root}/{rel}"
    pub rel: String,
    pub dir: String,    // rel's parent ("" at the root)
    pub name: String,
    pub kind: Kind,
    pub ext: String,    // without the dot
    pub size: u64,
    pub mtime: f64,
    pub root: usize,
    pub abs: String,
    pub absdir: String,
    pub url: String,    // "f/{root}/" + percent-encoded rel (Python urllib.parse.quote, '/' kept)
    pub tkey: String,   // sha1 hex of "{abs}\0{python_float_repr(mtime)}\0{size}"
    pub thumb: bool,
    pub at: f64,        // when it arrived or last changed (sort key)
    #[serde(skip)]
    pub first: f64,     // when it was first seen (0 for files found by the initial scan)
}

/// Images and models only; everything else is None.
pub fn kind_of(name: &str) -> Option<(Kind, String)> {
    let _ = name;
    todo!("watcher agent")
}

/// Build an Item exactly like Python's Watcher.make_item. `at` defaults to mtime.
pub fn make_item(roots: &[String], key: &Key, info: &FileInfo, at: Option<f64>) -> Item {
    let _ = (roots, key, info, at);
    todo!("watcher agent")
}
