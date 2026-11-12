//! Server-sent events. OWNED BY: integrator. Change only by agreement (see PORTING.md).
use crate::item::{Item, Kind};
use serde::Serialize;

/// Serializes to the same JSON the Python version sends: {"type":"add","item":{...}} etc.
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Event {
    Reset,
    Add { item: Item },
    Update { item: Item },
    Remove { id: String, kind: Kind, rel: String, root: usize },
}

/// Receives watcher events. Implemented by App; tests can implement it with a Vec.
pub trait Hub: Send + Sync {
    fn broadcast(&self, ev: Event);
}
