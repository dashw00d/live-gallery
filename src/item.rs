//! Shared data types.
use serde::Serialize;

pub const IMAGE_EXT: &[&str] = &[
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico",
];
pub const MODEL_EXT: &[&str] = &[".glb", ".gltf", ".obj", ".stl", ".ply", ".fbx"];
/// Noise: dependencies, caches, browser/app profiles agents' tooling leaves behind.
pub const SKIP_DIRS: &[&str] = &[
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".cache",
    "cache",
    "Cache",
    "site-packages",
    "vendor",
    "target",
    ".godot",
    ".import",
    "tool_profiles",
    "app_userdata",
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
    pub id: String, // "{root}/{rel}"
    pub rel: String,
    pub dir: String, // rel's parent ("" at the root)
    pub name: String,
    pub kind: Kind,
    pub ext: String, // without the dot
    pub size: u64,
    pub mtime: f64,
    pub root: usize,
    pub abs: String,
    pub absdir: String,
    pub url: String, // "f/{root}/" + percent-encoded rel (Python urllib.parse.quote, '/' kept)
    pub tkey: String, // sha1 hex of "{abs}\0{python_float_repr(mtime)}\0{size}"
    pub thumb: bool,
    pub at: f64, // when it arrived or last changed (sort key)
    #[serde(skip)]
    pub first: f64, // when it was first seen (0 for files found by the initial scan)
}

/// Python-compatible float representation for finite timestamps and intervals.
pub(crate) fn float_repr(x: f64) -> String {
    let s = format!("{:?}", x);
    if let Some((mantissa, exponent)) = s.split_once('e') {
        let exp: i32 = exponent.parse().unwrap();
        format!(
            "{}e{}{:02}",
            mantissa,
            if exp < 0 { "-" } else { "+" },
            exp.abs()
        )
    } else {
        s
    }
}

pub fn kind_of(name: &str) -> Option<(Kind, String)> {
    let base = name.rsplit('/').next().unwrap_or(name);
    let pos = base.rfind('.')?;
    if base[..pos].chars().all(|c| c == '.') {
        return None;
    }
    let ext = base[pos..].to_lowercase();
    let kind = if IMAGE_EXT.contains(&ext.as_str()) {
        Kind::Image
    } else if MODEL_EXT.contains(&ext.as_str()) {
        Kind::Model
    } else {
        return None;
    };
    Some((kind, ext))
}

pub fn make_item(roots: &[String], key: &Key, info: &FileInfo, at: Option<f64>) -> Item {
    let (root, rel) = key;
    let (dir, name) = rel.rsplit_once('/').unwrap_or(("", rel));
    let full = std::path::Path::new(&roots[*root]).join(rel);
    let abs = full.to_string_lossy().into_owned();
    let absdir = full.parent().unwrap().to_string_lossy().into_owned();
    let hash = format!("{}\0{}\0{}", abs, float_repr(info.mtime), info.size);
    let mut url = format!("f/{root}/");
    for b in rel.bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~/".contains(&b) {
            url.push(b as char);
        } else {
            url.push_str(&format!("%{b:02X}"));
        }
    }
    Item {
        id: format!("{root}/{rel}"),
        rel: rel.clone(),
        dir: dir.into(),
        name: name.into(),
        kind: info.kind,
        ext: info.ext[1..].into(),
        size: info.size,
        mtime: info.mtime,
        root: *root,
        abs,
        absdir,
        url,
        tkey: sha1_smol::Sha1::from(hash.as_bytes()).digest().to_string(),
        thumb: false,
        at: at.unwrap_or(info.mtime),
        first: 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn item_fields() {
        let item = make_item(
            &["/tmp/root".into()],
            &(0, "a b/é.png".into()),
            &FileInfo {
                size: 42,
                mtime: 1700000000.0,
                kind: Kind::Image,
                ext: ".png".into(),
            },
            None,
        );
        assert_eq!(item.url, "f/0/a%20b/%C3%A9.png");
        assert_eq!(item.tkey, "705338cd5dba5bc7a1ffa074fc7fbf7ffb9acd54");
    }
    #[test]
    fn item_float_repr() {
        for (v, expected) in [
            (1700000000.0, "1700000000.0"),
            (1.25, "1.25"),
            (1e-7, "1e-07"),
            (-0.0, "-0.0"),
        ] {
            assert_eq!(float_repr(v), expected);
        }
    }
}
