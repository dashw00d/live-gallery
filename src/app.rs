//! Owns the current Watcher, saved state and the SSE fan-out. OWNED BY: app agent. Port of Python `App`.
use crate::events::{Event, Hub};
use crate::watcher::{Watcher, WatcherOpts};
use std::collections::HashMap;
use std::sync::Arc;

pub struct App {
    // private fields are up to the app agent; must include a tokio::sync::broadcast::Sender<Arc<str>>
}

impl App {
    /// Loads state.json (empty object on any error).
    pub fn new(opts: WatcherOpts, initial: usize) -> Arc<App> {
        let _ = (opts, initial);
        todo!()
    }
    /// Roots saved by the page last time (state.json "roots"), possibly empty.
    pub fn saved_roots(&self) -> Vec<String> {
        todo!()
    }
    /// Replace the watcher; index in a background thread; broadcast reset before and after; save state if `save`.
    pub fn set_roots(self: &Arc<Self>, roots: Vec<String>, save: bool) {
        let _ = (roots, save);
        todo!()
    }
    /// The current watcher (cheap clone).
    pub fn watcher(&self) -> Arc<Watcher> {
        todo!()
    }
    /// GET /api/list body. `q` is the decoded query string (first value per key).
    pub fn listing(&self, q: &HashMap<String, String>) -> serde_json::Value {
        let _ = q;
        todo!()
    }
    /// POST /api/thumb: store body as the item's thumbnail if `version` still equals its mtime.
    pub fn save_thumb(&self, id: &str, version: &str, body: &[u8]) -> bool {
        let _ = (id, version, body);
        todo!()
    }
    /// One receiver per SSE client; each message is the JSON of one Event.
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<Arc<str>> {
        todo!()
    }
}

impl Hub for App {
    fn broadcast(&self, ev: Event) {
        let _ = ev;
        todo!()
    }
}
