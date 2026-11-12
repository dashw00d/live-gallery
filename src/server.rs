//! HTTP routes, file serving, SSE. OWNED BY: server agent. Port of Python `make_handler`.
use crate::app::App;
use std::sync::Arc;

pub const PAGE: &str = include_str!("../assets/index.html");
pub const KIT_JS: &str = include_str!("../assets/kit.js");
pub const WORKER_JS: &str = include_str!("../assets/worker.js");

/// Serve until the process is stopped (Ctrl+C handled by main).
pub async fn serve(app: Arc<App>, listener: tokio::net::TcpListener) -> std::io::Result<()> {
    let _ = (app, listener);
    todo!()
}
