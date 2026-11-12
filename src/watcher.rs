//! Folder scanning + live watching (inotify on Linux, polling elsewhere or with --poll).
//! OWNED BY: watcher agent. Port of Python `Inotify` + `Watcher`.
use crate::events::Hub;
use crate::item::{Item, Key};
use std::sync::Arc;

#[derive(Clone, Debug)]
pub struct WatcherOpts {
    pub interval: f64,
    pub exclude: Vec<String>,
    pub poll: bool,
}

pub struct Watcher {
    // private fields are up to the watcher agent
}

impl Watcher {
    /// `roots` are absolute, normalized folder paths (already validated by util::norm_roots).
    pub fn new(roots: Vec<String>, opts: &WatcherOpts, hub: Arc<dyn Hub>) -> Arc<Watcher> {
        let _ = (roots, opts, hub);
        todo!()
    }
    /// Blocking initial scan (items get `first = 0`, no events), then spawns the watch loop thread.
    pub fn start(self: &Arc<Self>) {
        todo!()
    }
    /// Stops the loop within ~1s; after stop() no more events are broadcast.
    pub fn stop(&self) {
        todo!()
    }
    pub fn roots(&self) -> &[String] {
        todo!()
    }
    /// Copy of all current items (any order).
    pub fn snapshot(&self) -> Vec<Item> {
        todo!()
    }
    pub fn get(&self, key: &Key) -> Option<Item> {
        let _ = key;
        todo!()
    }
    pub fn len(&self) -> usize {
        todo!()
    }
    /// "inotify, N folders" or "polling every {interval}s" (Python formats the float, e.g. "1.0s").
    pub fn mode(&self) -> String {
        todo!()
    }
}
