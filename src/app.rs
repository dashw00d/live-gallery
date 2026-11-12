//! Application state and SSE fan-out.
use crate::events::{Event, Hub};
use crate::item::{Item, Kind};
use crate::util::{state_path, thumb_dir, thumb_file};
use crate::watcher::{Watcher, WatcherOpts};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::Instant,
};
struct State {
    watcher: Option<Arc<Watcher>>,
    indexing: bool,
    generation: u64,
    saved: Value,
}
pub struct App {
    opts: WatcherOpts,
    initial: usize,
    state: Mutex<State>,
    tx: tokio::sync::broadcast::Sender<Arc<str>>,
}
impl App {
    pub fn new(opts: WatcherOpts, initial: usize) -> Arc<App> {
        let saved = std::fs::read(state_path())
            .ok()
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
            .filter(Value::is_object)
            .unwrap_or_else(|| json!({}));
        let (tx, _) = tokio::sync::broadcast::channel(4096);
        Arc::new(Self {
            opts,
            initial,
            state: Mutex::new(State {
                watcher: None,
                indexing: false,
                generation: 0,
                saved,
            }),
            tx,
        })
    }
    pub fn saved_roots(&self) -> Vec<String> {
        serde_json::from_value(
            self.state
                .lock()
                .unwrap()
                .saved
                .get("roots")
                .cloned()
                .unwrap_or(json!([])),
        )
        .unwrap_or_default()
    }
    pub fn set_roots(self: &Arc<Self>, roots: Vec<String>, save: bool) {
        let w = Watcher::new(roots.clone(), &self.opts, self.clone());
        let (old, generation) = {
            let mut s = self.state.lock().unwrap();
            let old = s.watcher.replace(w.clone());
            s.indexing = true;
            s.generation += 1;
            if save {
                let mut recent = s
                    .saved
                    .get("recent")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                recent.retain(|r| *r != json!(roots));
                recent.truncate(11);
                recent.insert(0, json!(roots));
                s.saved["roots"] = json!(roots);
                s.saved["recent"] = json!(recent);
                let path = state_path();
                let result = (|| -> std::io::Result<()> {
                    std::fs::create_dir_all(path.parent().unwrap())?;
                    let tmp = path.with_extension("json.tmp");
                    std::fs::write(&tmp, serde_json::to_vec_pretty(&s.saved)?)?;
                    std::fs::rename(tmp, path)
                })();
                if let Err(e) = result {
                    eprintln!("could not save state: {e}");
                }
            }
            (old, s.generation)
        };
        if let Some(old) = old {
            old.stop()
        }
        self.broadcast(Event::Reset);
        println!("indexing {} ...", roots.join(", "));
        let app = self.clone();
        std::thread::spawn(move || {
            let t = Instant::now();
            w.start();
            let current = {
                let mut s = app.state.lock().unwrap();
                if s.generation == generation {
                    s.indexing = false;
                    true
                } else {
                    false
                }
            };
            if current {
                println!(
                    "watching {}: {} images/models, indexed in {:.1}s ({})",
                    roots.join(", "),
                    w.len(),
                    t.elapsed().as_secs_f64(),
                    w.mode()
                );
                app.broadcast(Event::Reset);
            }
        });
    }
    pub fn watcher(&self) -> Arc<Watcher> {
        self.state
            .lock()
            .unwrap()
            .watcher
            .as_ref()
            .expect("watcher not initialized")
            .clone()
    }
    pub fn listing(&self, q: &HashMap<String, String>) -> Value {
        let (w, indexing, recent) = {
            let s = self.state.lock().unwrap();
            (
                s.watcher.as_ref().expect("watcher not initialized").clone(),
                s.indexing,
                s.saved.get("recent").cloned().unwrap_or(json!([])),
            )
        };
        listing_items(
            w.snapshot(),
            q,
            self.initial,
            w.roots(),
            indexing,
            &w.mode(),
            recent,
        )
    }
    pub fn save_thumb(&self, id: &str, version: &str, body: &[u8]) -> bool {
        let (ri, rel) = id.split_once('/').unwrap_or((id, ""));
        let (Ok(ri), Ok(version)) = (ri.parse(), version.parse::<f64>()) else {
            return false;
        };
        let Some(item) = self.watcher().get(&(ri, rel.to_string())) else {
            return false;
        };
        if item.mtime != version {
            return false;
        }
        let result = (|| -> std::io::Result<()> {
            std::fs::create_dir_all(thumb_dir())?;
            let path = thumb_file(&item.tkey);
            let tmp = path.with_extension(format!("{:?}.tmp", std::thread::current().id()));
            std::fs::write(&tmp, body)?;
            std::fs::rename(tmp, path)
        })();
        if let Err(e) = result {
            eprintln!("could not save thumbnail: {e}");
            return false;
        }
        true
    }
    pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<Arc<str>> {
        self.tx.subscribe()
    }
}
impl Hub for App {
    fn broadcast(&self, ev: Event) {
        if let Ok(s) = serde_json::to_string(&ev) {
            let _ = self.tx.send(Arc::from(s));
        }
    }
}
fn listing_items(
    mut items: Vec<Item>,
    q: &HashMap<String, String>,
    initial: usize,
    roots: &[String],
    indexing: bool,
    mode: &str,
    recent: Value,
) -> Value {
    let all = items.len();
    let parsed = (|| -> Option<(Option<i64>, usize, Option<(f64, f64, &str)>)> {
        let root = match q.get("root") {
            Some(s) => Some(s.parse().ok()?),
            None => None,
        };
        let limit = match q.get("limit").filter(|s| !s.is_empty()) {
            Some(s) => s.parse::<i64>().ok()?.clamp(1, 500) as usize,
            None => initial.clamp(1, 500),
        };
        let before = match q.get("before") {
            Some(s) => Some((
                s.parse().ok()?,
                q.get("before_m")
                    .filter(|s| !s.is_empty())
                    .map(|s| s.parse())
                    .transpose()
                    .ok()?
                    .unwrap_or(0.0),
                q.get("before_id").map(String::as_str).unwrap_or(""),
            )),
            None => None,
        };
        Some((root, limit, before))
    })();
    let (root, limit, before) = parsed.unwrap_or((None, initial, None));
    let kind = q.get("kind").map(String::as_str).unwrap_or("");
    let text = q.get("q").map(|s| s.to_lowercase()).unwrap_or_default();
    items.retain(|i| {
        (kind.is_empty()
            || kind
                == match i.kind {
                    Kind::Image => "image",
                    Kind::Model => "model",
                })
            && root.is_none_or(|r| i.root as i64 == r)
            && i.rel.to_lowercase().contains(&text)
    });
    let total = items.len();
    if let Some((at, m, id)) = before {
        items.retain(|i| (i.at, i.mtime, i.id.as_str()) < (at, m, id));
    }
    items.sort_by(|a, b| {
        b.at.total_cmp(&a.at)
            .then_with(|| b.mtime.total_cmp(&a.mtime))
            .then_with(|| b.id.cmp(&a.id))
    });
    let more = items.len() > limit;
    items.truncate(limit);
    for i in &mut items {
        i.thumb = thumb_file(&i.tkey).exists()
    }
    json!({"roots":roots,"total":total,"all":all,"items":items,"more":more,"indexing":indexing,"mode":mode,"recent":recent})
}
#[cfg(test)]
mod tests {
    use super::*;
    fn item(id: &str, at: f64, kind: Kind, root: usize) -> Item {
        Item {
            id: id.into(),
            rel: id.into(),
            dir: String::new(),
            name: id.into(),
            kind,
            ext: String::new(),
            size: 0,
            mtime: at,
            root,
            abs: String::new(),
            absdir: String::new(),
            url: String::new(),
            tkey: format!("unlikely-test-{id}"),
            thumb: false,
            at,
            first: 0.0,
        }
    }
    #[test]
    fn pagination_filters_and_cursor() {
        let items = vec![
            item("a", 1.0, Kind::Image, 0),
            item("b", 2.0, Kind::Model, 1),
            item("c", 3.0, Kind::Image, 0),
        ];
        let mut q = HashMap::new();
        q.insert("kind".into(), "image".into());
        q.insert("limit".into(), "1".into());
        let page = listing_items(items.clone(), &q, 60, &[], false, "", json!([]));
        assert_eq!(page["total"], 2);
        assert_eq!(page["all"], 3);
        assert_eq!(page["items"][0]["id"], "c");
        assert_eq!(page["more"], true);
        q.insert("before".into(), "3".into());
        q.insert("before_m".into(), "3".into());
        q.insert("before_id".into(), "c".into());
        let next = listing_items(items, &q, 60, &[], false, "", json!([]));
        assert_eq!(next["items"][0]["id"], "a");
        assert_eq!(next["more"], false);
    }
    #[test]
    fn broadcast_without_receivers() {
        let app = App::new(
            WatcherOpts {
                interval: 1.0,
                exclude: vec![],
                poll: true,
            },
            60,
        );
        app.broadcast(Event::Reset);
        let mut rx = app.subscribe();
        app.broadcast(Event::Reset);
        assert_eq!(&*rx.try_recv().unwrap(), "{\"type\":\"reset\"}");
    }
}
