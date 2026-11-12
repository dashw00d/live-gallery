//! HTTP routes, file serving, SSE.
use crate::{app::App, util};
use axum::{
    Json, Router,
    body::{Body, to_bytes},
    extract::State,
    http::{Method, Request, StatusCode, header},
    response::{IntoResponse, Response},
    routing::any,
};
use percent_encoding::percent_decode_str;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    path::{Component, Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::io::AsyncReadExt;
use tokio_util::io::ReaderStream;

pub const PAGE: &str = include_str!("../assets/index.html");
pub const KIT_JS: &str = include_str!("../assets/kit.js");
pub const WORKER_JS: &str = include_str!("../assets/worker.js");
const IMMUTABLE: &str = "private, max-age=31536000, immutable";

pub async fn serve(app: Arc<App>, listener: tokio::net::TcpListener) -> std::io::Result<()> {
    axum::serve(
        listener,
        Router::new().fallback(any(handle)).with_state(app),
    )
    .await
}

fn query(raw: &str) -> HashMap<String, String> {
    fn decode(s: &str) -> String {
        percent_decode_str(&s.replace('+', " "))
            .decode_utf8_lossy()
            .into_owned()
    }
    let mut result = HashMap::new();
    for pair in raw.split('&').filter(|s| !s.is_empty()) {
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        result.entry(decode(k)).or_insert_with(|| decode(v));
    }
    result
}
fn valid_key(s: &str) -> bool {
    s.len() == 40
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn normalized_rel(s: &str) -> String {
    let mut parts = Vec::new();
    for c in Path::new(s).components() {
        match c {
            Component::Normal(p) => parts.push(p.to_string_lossy().into_owned()),
            Component::ParentDir if parts.last().is_some_and(|p| p != "..") => {
                parts.pop();
            }
            Component::ParentDir => parts.push("..".into()),
            Component::RootDir => parts.clear(),
            _ => {}
        }
    }
    let joined = parts.join("/");
    if Path::new(s).is_absolute() {
        format!("/{joined}")
    } else if joined.is_empty() {
        ".".into()
    } else {
        joined
    }
}
fn content_type(path: &Path) -> String {
    match path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "glb" => "model/gltf-binary",
        "gltf" => "model/gltf+json",
        "webp" => "image/webp",
        "avif" => "image/avif",
        "svg" => "image/svg+xml",
        "stl" => "model/stl",
        _ => {
            return mime_guess::from_path(path)
                .first_or_octet_stream()
                .essence_str()
                .to_owned();
        }
    }
    .to_owned()
}
fn watch_paths(body: &[u8]) -> Option<Vec<String>> {
    let value: Value = serde_json::from_slice(body).ok()?;
    match value.get("roots")? {
        Value::String(s) => Some(vec![s.clone()]),
        Value::Array(a) => a.iter().map(|v| v.as_str().map(str::to_owned)).collect(),
        _ => None,
    }
}
fn json_response(value: Value, status: StatusCode) -> Response {
    let mut r = (status, Json(value)).into_response();
    r.headers_mut()
        .insert(header::CACHE_CONTROL, "no-store".parse().unwrap());
    r
}
fn error(message: &str, status: StatusCode) -> Response {
    json_response(json!({"error": message}), status)
}
fn static_response(body: &'static str, kind: &'static str) -> Response {
    (
        [
            (header::CONTENT_TYPE, kind),
            (header::CACHE_CONTROL, "no-store"),
        ],
        body,
    )
        .into_response()
}
async fn stream_file(path: PathBuf, kind: String, cache: &'static str) -> Response {
    let Ok(file) = tokio::fs::File::open(path).await else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Ok(meta) = file.metadata().await else {
        return StatusCode::NOT_FOUND.into_response();
    };
    if !meta.is_file() {
        return StatusCode::NOT_FOUND.into_response();
    }
    let mut r = Body::from_stream(ReaderStream::new(file)).into_response();
    let h = r.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        kind.parse()
            .unwrap_or_else(|_| "application/octet-stream".parse().unwrap()),
    );
    h.insert(
        header::CONTENT_LENGTH,
        meta.len().to_string().parse().unwrap(),
    );
    h.insert(header::CACHE_CONTROL, cache.parse().unwrap());
    r
}
async fn handle(State(app): State<Arc<App>>, req: Request<Body>) -> Response {
    let path = req.uri().path().to_owned();
    let q = query(req.uri().query().unwrap_or(""));
    match (req.method(), path.as_str()) {
        (&Method::GET, "/") => static_response(PAGE, "text/html; charset=utf-8"),
        (&Method::GET, "/kit.js") => static_response(KIT_JS, "text/javascript; charset=utf-8"),
        (&Method::GET, "/worker.js") => {
            static_response(WORKER_JS, "text/javascript; charset=utf-8")
        }
        (&Method::GET, "/api/list") => json_response(app.listing(&q), StatusCode::OK),
        (&Method::GET, "/api/dirs") => json_response(
            json!({"dirs":util::complete_dirs(q.get("prefix").map_or("", String::as_str), 40)}),
            StatusCode::OK,
        ),
        (&Method::GET, "/events") => {
            let mut rx = app.subscribe();
            let (tx, stream) =
                tokio::sync::mpsc::channel::<Result<String, std::convert::Infallible>>(8);
            tokio::spawn(async move {
                if tx.send(Ok(": hi\n\n".into())).await.is_err() {
                    return;
                }
                loop {
                    let message = tokio::select! {
                        _ = tx.closed() => break,
                        result = tokio::time::timeout(Duration::from_secs(15), rx.recv()) => match result {
                            Ok(Ok(s)) => format!("data: {s}\n\n"),
                            Ok(Err(tokio::sync::broadcast::error::RecvError::Lagged(_))) => "data: {\"type\":\"reset\"}\n\n".into(),
                            Ok(Err(tokio::sync::broadcast::error::RecvError::Closed)) => break,
                            Err(_) => ": ping\n\n".into(),
                        }
                    };
                    if tx.send(Ok(message)).await.is_err() {
                        break;
                    }
                }
            });
            (
                [
                    (header::CONTENT_TYPE, "text/event-stream"),
                    (header::CACHE_CONTROL, "no-cache"),
                ],
                Body::from_stream(tokio_stream::wrappers::ReceiverStream::new(stream)),
            )
                .into_response()
        }
        (&Method::GET, _) if path.starts_with("/f/") => {
            let Some((root, rel)) = path[3..].split_once('/') else {
                return StatusCode::NOT_FOUND.into_response();
            };
            let Ok(index) = root.parse::<usize>() else {
                return StatusCode::NOT_FOUND.into_response();
            };
            let watcher = app.watcher();
            let Some(root) = watcher.roots().get(index) else {
                return StatusCode::NOT_FOUND.into_response();
            };
            let rel = percent_decode_str(rel).decode_utf8_lossy().into_owned();
            let Ok(real_root) = tokio::fs::canonicalize(root).await else {
                return StatusCode::NOT_FOUND.into_response();
            };
            let Ok(full) = tokio::fs::canonicalize(Path::new(root).join(&rel)).await else {
                return StatusCode::NOT_FOUND.into_response();
            };
            if !full.starts_with(&real_root)
                && watcher.get(&(index, normalized_rel(&rel))).is_none()
            {
                return StatusCode::NOT_FOUND.into_response();
            }
            let kind = content_type(&full);
            stream_file(
                full,
                kind,
                if q.contains_key("v") {
                    IMMUTABLE
                } else {
                    "no-cache"
                },
            )
            .await
        }
        (&Method::GET, _) if path.starts_with("/t/") => {
            let key = &path[3..];
            if !valid_key(key) {
                return StatusCode::NOT_FOUND.into_response();
            }
            let file = util::thumb_file(key);
            let Ok(mut f) = tokio::fs::File::open(&file).await else {
                return StatusCode::NOT_FOUND.into_response();
            };
            let mut head = [0; 16];
            let Ok(n) = f.read(&mut head).await else {
                return StatusCode::NOT_FOUND.into_response();
            };
            stream_file(
                file,
                util::image_type(&head[..n])
                    .unwrap_or("application/octet-stream")
                    .into(),
                IMMUTABLE,
            )
            .await
        }
        (&Method::POST, "/api/thumb" | "/api/watch") => {
            let too_large = req.headers().get(header::CONTENT_LENGTH).is_some_and(|v| {
                v.to_str()
                    .ok()
                    .and_then(|s| s.parse::<u64>().ok())
                    .is_none_or(|n| n > util::THUMB_MAX as u64)
            });
            if too_large {
                return StatusCode::PAYLOAD_TOO_LARGE.into_response();
            }
            let ctype = req
                .headers()
                .get(header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("")
                .to_owned();
            let Ok(body) = to_bytes(req.into_body(), util::THUMB_MAX).await else {
                return StatusCode::PAYLOAD_TOO_LARGE.into_response();
            };
            if path == "/api/thumb" {
                if !ctype.starts_with("image/") || util::image_type(&body).is_none() {
                    return error("expected an image", StatusCode::UNSUPPORTED_MEDIA_TYPE);
                }
                return json_response(
                    json!({"ok":app.save_thumb(q.get("id").map_or("", String::as_str), q.get("v").map_or("", String::as_str), &body)}),
                    StatusCode::OK,
                );
            }
            if !ctype.starts_with("application/json") {
                return error("expected JSON", StatusCode::UNSUPPORTED_MEDIA_TYPE);
            }
            let Some(paths) = watch_paths(&body) else {
                return error("bad request", StatusCode::BAD_REQUEST);
            };
            let (roots, bad) = util::norm_roots(&paths);
            if !bad.is_empty() {
                return error(
                    &format!("not a folder: {}", bad.join(", ")),
                    StatusCode::BAD_REQUEST,
                );
            }
            if roots.is_empty() {
                return error("enter a folder path", StatusCode::BAD_REQUEST);
            }
            let saved = roots.clone();
            if tokio::task::spawn_blocking(move || app.set_roots(saved, true))
                .await
                .is_err()
            {
                return StatusCode::INTERNAL_SERVER_ERROR.into_response();
            }
            json_response(json!({"ok":true,"roots":roots}), StatusCode::OK)
        }
        _ => StatusCode::NOT_FOUND.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn query_first_and_decoding() {
        let q = query("x=a+b&x=second&v=&p=%2Ftmp");
        assert_eq!(q["x"], "a b");
        assert_eq!(q["v"], "");
        assert_eq!(q["p"], "/tmp");
    }
    #[test]
    fn keys_and_paths() {
        assert!(valid_key(&"a0".repeat(20)));
        assert!(!valid_key(&"A".repeat(40)));
        assert!(!valid_key("abc"));
        assert_eq!(normalized_rel("a/../b/./c"), "b/c");
        assert_eq!(normalized_rel("../../x"), "../../x");
    }
    #[test]
    fn types_and_watch() {
        assert_eq!(content_type(Path::new("foo.GLB")), "model/gltf-binary");
        assert_eq!(content_type(Path::new("a.stl")), "model/stl");
        assert_eq!(
            watch_paths(br#"{"roots":"/tmp"}"#),
            Some(vec!["/tmp".into()])
        );
        assert!(watch_paths(br#"{"roots":["x",1]}"#).is_none());
    }
}
