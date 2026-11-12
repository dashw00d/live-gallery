//! Recursive scanning and live watching (inotify on Linux, polling elsewhere or with --poll).
//! Scans run without holding any lock; the item map is only locked briefly, so listings and file
//! requests never wait for a walk of a big tree.
use crate::events::{Event, Hub};
use crate::item::{FileInfo, Item, Key, SKIP_DIRS, float_repr, kind_of, make_item};
use crate::util::SETTLE;
#[cfg(target_os = "linux")]
use inotify::{EventMask, Inotify, WatchDescriptor, WatchMask};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Debug)]
pub struct WatcherOpts {
    pub interval: f64,
    pub exclude: Vec<String>,
    pub poll: bool,
}

#[cfg(target_os = "linux")]
struct Ino {
    ino: Inotify,
    wds: HashMap<WatchDescriptor, (usize, PathBuf)>,
    warned: bool,
}

pub struct Watcher {
    roots: Vec<String>,
    opts: WatcherOpts,
    hub: Arc<dyn Hub>,
    stopped: AtomicBool,
    items: Mutex<HashMap<Key, Item>>,
    #[cfg(target_os = "linux")]
    ino: Option<Mutex<Ino>>,
    thread: Mutex<Option<thread::JoinHandle<()>>>,
}

fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64()
}

fn info(path: &Path, name: &str) -> Option<FileInfo> {
    let (kind, ext) = kind_of(name)?;
    let md = std::fs::metadata(path).ok()?;
    if md.is_dir() {
        return None;
    }
    let mtime = match md.modified().ok()?.duration_since(UNIX_EPOCH) {
        Ok(t) => t.as_secs_f64(),
        Err(e) => -e.duration().as_secs_f64(),
    };
    Some(FileInfo { size: md.len(), mtime, kind, ext })
}

fn same(a: &FileInfo, size: u64, mtime: f64) -> bool {
    a.size == size && a.mtime == mtime
}

impl Watcher {
    pub fn new(roots: Vec<String>, opts: &WatcherOpts, hub: Arc<dyn Hub>) -> Arc<Watcher> {
        #[cfg(target_os = "linux")]
        let ino = if opts.poll {
            None
        } else {
            match Inotify::init() {
                Ok(ino) => Some(Mutex::new(Ino { ino, wds: HashMap::new(), warned: false })),
                Err(e) => {
                    eprintln!("inotify unavailable ({e}); polling every {}s", float_repr(opts.interval));
                    None
                }
            }
        };
        Arc::new(Self {
            roots,
            opts: opts.clone(),
            hub,
            stopped: AtomicBool::new(false),
            items: Mutex::new(HashMap::new()),
            #[cfg(target_os = "linux")]
            ino,
            thread: Mutex::new(None),
        })
    }

    fn stopped(&self) -> bool {
        self.stopped.load(Ordering::SeqCst)
    }

    fn skip(&self, name: &str) -> bool {
        SKIP_DIRS.contains(&name) || self.opts.exclude.iter().any(|x| x == name)
    }

    #[cfg(target_os = "linux")]
    fn add_watch(&self, ri: usize, dir: &Path) {
        let Some(ino) = &self.ino else { return };
        let mut ino = ino.lock().unwrap();
        let mask = WatchMask::CLOSE_WRITE
            | WatchMask::MOVED_FROM
            | WatchMask::MOVED_TO
            | WatchMask::CREATE
            | WatchMask::DELETE
            | WatchMask::ONLYDIR
            | WatchMask::DONT_FOLLOW
            | WatchMask::EXCL_UNLINK;
        match ino.ino.watches().add(dir, mask) {
            Ok(wd) => {
                ino.wds.insert(wd, (ri, dir.to_path_buf()));
            }
            Err(e) if e.raw_os_error() == Some(libc_enospc()) && !ino.warned => {
                ino.warned = true;
                eprintln!(
                    "WARNING: out of inotify watches; some folders are not watched. Narrow the folders, \
                     add -x excludes, or raise fs.inotify.max_user_watches."
                );
            }
            Err(_) => {}
        }
    }

    fn walk(&self, ri: usize, top: &Path) -> HashMap<Key, FileInfo> {
        let mut found = HashMap::new();
        let mut stack = vec![top.to_path_buf()];
        while let Some(dir) = stack.pop() {
            if self.stopped() {
                break;
            }
            #[cfg(target_os = "linux")]
            self.add_watch(ri, &dir); // watch before listing, so nothing slips between
            let Ok(entries) = std::fs::read_dir(&dir) else { continue };
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                    if !self.skip(&name) {
                        stack.push(entry.path());
                    }
                    continue;
                }
                let path = entry.path();
                if let Some(v) = info(&path, &name) {
                    if let Some(key) = self.key_of(ri, &path) {
                        found.insert(key, v);
                    }
                }
            }
        }
        found
    }

    fn key_of(&self, ri: usize, path: &Path) -> Option<Key> {
        let rel = path.strip_prefix(&self.roots[ri]).ok()?;
        Some((ri, rel.to_string_lossy().replace(std::path::MAIN_SEPARATOR, "/")))
    }

    fn scan(&self) -> HashMap<Key, FileInfo> {
        let mut all = HashMap::new();
        for (i, r) in self.roots.iter().enumerate() {
            all.extend(self.walk(i, Path::new(r)));
        }
        all
    }

    fn broadcast(&self, ev: Event) {
        if !self.stopped() {
            self.hub.broadcast(ev);
        }
    }

    fn upsert(&self, key: Key, v: FileInfo, at: Option<f64>) {
        let t = now();
        let item = {
            let mut items = self.items.lock().unwrap();
            let old = items.get(&key);
            if old.is_some_and(|o| o.size == v.size && o.mtime == v.mtime) {
                return;
            }
            let first = old.map(|o| o.first);
            let mut item = make_item(&self.roots, &key, &v, Some(at.unwrap_or(t)));
            item.first = first.unwrap_or(t);
            items.insert(key, item.clone());
            (item, first.is_some())
        };
        let (item, existed) = item;
        // a file still settling within 5s of first appearing stays "new"
        let update = existed && t - item.first > 5.0;
        println!("[{}] {:<6} {}", clock(), if update { "update" } else { "add" }, item.abs);
        self.broadcast(if update { Event::Update { item } } else { Event::Add { item } });
    }

    fn remove(&self, key: &Key) {
        let item = self.items.lock().unwrap().remove(key);
        if let Some(item) = item {
            self.broadcast(Event::Remove { id: item.id, kind: item.kind, rel: item.rel, root: item.root });
        }
    }

    fn sync(&self, cur: HashMap<Key, FileInfo>) {
        let gone: Vec<Key> = {
            let items = self.items.lock().unwrap();
            items.keys().filter(|k| !cur.contains_key(*k)).cloned().collect()
        };
        for (k, v) in cur {
            self.upsert(k, v, None);
        }
        for k in gone {
            self.remove(&k);
        }
    }

    /// Blocking initial scan (items get `first = 0`, no events), then spawns the watch loop thread.
    pub fn start(self: &Arc<Self>) {
        let found = self.scan();
        {
            let mut items = self.items.lock().unwrap();
            for (k, v) in found {
                let item = make_item(&self.roots, &k, &v, None);
                items.insert(k, item);
            }
        }
        if self.stopped() {
            return;
        }
        let this = Arc::clone(self);
        *self.thread.lock().unwrap() = Some(thread::spawn(move || this.run()));
    }

    /// Stops the loop within ~1s; after stop() no more events are broadcast.
    pub fn stop(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        // Don't join: stop() is called from request handlers, and the loop notices within 50ms.
        self.thread.lock().unwrap().take();
    }

    pub fn roots(&self) -> &[String] {
        &self.roots
    }

    pub fn snapshot(&self) -> Vec<Item> {
        self.items.lock().unwrap().values().cloned().collect()
    }

    pub fn get(&self, key: &Key) -> Option<Item> {
        self.items.lock().unwrap().get(key).cloned()
    }

    pub fn len(&self) -> usize {
        self.items.lock().unwrap().len()
    }

    pub fn mode(&self) -> String {
        #[cfg(target_os = "linux")]
        if let Some(ino) = &self.ino {
            return format!("inotify, {} folders", ino.lock().unwrap().wds.len());
        }
        format!("polling every {}s", float_repr(self.opts.interval))
    }

    fn run(&self) {
        #[cfg(target_os = "linux")]
        if self.ino.is_some() {
            return self.inotify_loop();
        }
        self.poll_loop();
    }

    fn poll_loop(&self) {
        let mut pending: HashMap<Key, (u64, f64)> = HashMap::new();
        let step = Duration::from_millis(50);
        let mut next = now() + self.opts.interval.max(0.01);
        while !self.stopped() {
            thread::sleep(step);
            if now() < next {
                continue;
            }
            let cur = self.scan();
            if self.stopped() {
                break;
            }
            let known: HashMap<Key, (u64, f64)> = {
                let items = self.items.lock().unwrap();
                items.iter().map(|(k, i)| (k.clone(), (i.size, i.mtime))).collect()
            };
            for (k, v) in &cur {
                let sig = (v.size, v.mtime);
                if known.get(k) == Some(&sig) {
                    pending.remove(k);
                } else if pending.get(k) != Some(&sig) {
                    pending.insert(k.clone(), sig); // still being written; wait one more scan
                } else {
                    pending.remove(k);
                    self.upsert(k.clone(), v.clone(), None);
                }
            }
            for k in known.keys().filter(|k| !cur.contains_key(*k)) {
                self.remove(k);
            }
            pending.retain(|k, _| cur.contains_key(k));
            next = now() + self.opts.interval.max(0.01);
        }
    }

    #[cfg(target_os = "linux")]
    fn inotify_loop(&self) {
        let ino = self.ino.as_ref().unwrap();
        let mut young: HashMap<Key, (FileInfo, f64)> = HashMap::new();
        let mut buf = vec![0u8; 1 << 16];
        let mut next_settle = 0.0;
        while !self.stopped() {
            let events: Vec<(WatchDescriptor, EventMask, Option<String>)> = {
                let mut g = ino.lock().unwrap();
                match g.ino.read_events(&mut buf) {
                    Ok(es) => es
                        .map(|e| (e.wd, e.mask, e.name.map(|n| n.to_string_lossy().into_owned())))
                        .collect(),
                    Err(_) => Vec::new(),
                }
            };
            if events.is_empty() {
                thread::sleep(Duration::from_millis(50));
            }
            if self.stopped() {
                break;
            }
            if !young.is_empty() && now() >= next_settle {
                next_settle = now() + 0.2;
                self.settle(&mut young);
            }
            for (wd, mask, name) in events {
                self.handle_event(ino, &mut young, wd, mask, name);
            }
        }
    }

    /// Announce held files once their size and time have stopped changing.
    #[cfg(target_os = "linux")]
    fn settle(&self, young: &mut HashMap<Key, (FileInfo, f64)>) {
        let t = now();
        let due: Vec<Key> = young.iter().filter(|(_, (_, d))| t >= *d).map(|(k, _)| k.clone()).collect();
        for k in due {
            let (old, _) = young.remove(&k).unwrap();
            let path = Path::new(&self.roots[k.0]).join(&k.1);
            let name = k.1.rsplit('/').next().unwrap_or(&k.1).to_owned();
            let Some(v) = info(&path, &name) else { continue };
            if same(&old, v.size, v.mtime) {
                self.upsert(k, v, None);
            } else {
                young.insert(k, (v, t + SETTLE));
            }
        }
    }

    #[cfg(target_os = "linux")]
    fn handle_event(
        &self,
        ino: &Mutex<Ino>,
        young: &mut HashMap<Key, (FileInfo, f64)>,
        wd: WatchDescriptor,
        mask: EventMask,
        name: Option<String>,
    ) {
        if mask.contains(EventMask::Q_OVERFLOW) {
            eprintln!("event queue overflowed; rescanning");
            let cur = self.scan();
            self.sync(cur);
            return;
        }
        if mask.contains(EventMask::IGNORED) {
            ino.lock().unwrap().wds.remove(&wd);
            return;
        }
        let Some((ri, dir)) = ino.lock().unwrap().wds.get(&wd).cloned() else { return };
        let Some(name) = name.filter(|n| !n.is_empty()) else { return };
        let path = dir.join(&name);
        if mask.contains(EventMask::ISDIR) {
            if self.skip(&name) {
                return;
            }
            if mask.intersects(EventMask::CREATE | EventMask::MOVED_TO) {
                // A whole folder arrived (copied or moved in). Files changed in the last moments may
                // still be mid-copy: hold those until they finish instead of announcing them twice.
                let at = now();
                for (k, v) in self.walk(ri, &path) {
                    if at - v.mtime < SETTLE {
                        young.insert(k, (v, at + SETTLE));
                    } else {
                        self.upsert(k, v, Some(at));
                    }
                }
            } else if mask.intersects(EventMask::MOVED_FROM | EventMask::DELETE) {
                self.drop_tree(ino, young, &path);
            }
            return;
        }
        if kind_of(&name).is_none() {
            return;
        }
        let Some(key) = self.key_of(ri, &path) else { return };
        if mask.intersects(EventMask::CLOSE_WRITE | EventMask::MOVED_TO) {
            if let Some(v) = info(&path, &name) {
                young.remove(&key);
                self.upsert(key, v, None);
            }
        } else if mask.intersects(EventMask::DELETE | EventMask::MOVED_FROM) {
            young.remove(&key);
            self.remove(&key);
        }
    }

    #[cfg(target_os = "linux")]
    fn drop_tree(&self, ino: &Mutex<Ino>, young: &mut HashMap<Key, (FileInfo, f64)>, path: &Path) {
        {
            let mut g = ino.lock().unwrap();
            let wds: Vec<WatchDescriptor> =
                g.wds.iter().filter(|(_, (_, p))| p.starts_with(path)).map(|(w, _)| w.clone()).collect();
            for w in wds {
                g.wds.remove(&w);
                let _ = g.ino.watches().remove(w);
            }
        }
        let gone: Vec<Key> = {
            let items = self.items.lock().unwrap();
            items.iter().filter(|(_, i)| Path::new(&i.abs).starts_with(path)).map(|(k, _)| k.clone()).collect()
        };
        for k in gone {
            self.remove(&k);
        }
        young.retain(|k, _| !Path::new(&self.roots[k.0]).join(&k.1).starts_with(path));
    }
}

#[cfg(target_os = "linux")]
fn libc_enospc() -> i32 {
    28
}

/// Local HH:MM:SS for console lines, like Python's time.strftime('%H:%M:%S').
fn clock() -> String {
    let offset = local_offset_secs();
    let secs = (now() as i64 + offset).rem_euclid(86_400);
    format!("{:02}:{:02}:{:02}", secs / 3600, secs / 60 % 60, secs % 60)
}

/// UTC offset from `date +%z` once per process (no time-zone crate needed); 0 if unavailable.
fn local_offset_secs() -> i64 {
    static OFFSET: std::sync::OnceLock<i64> = std::sync::OnceLock::new();
    *OFFSET.get_or_init(|| {
        let out = std::process::Command::new("date").arg("+%z").output().ok();
        let s = out.map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned()).unwrap_or_default();
        if s.len() != 5 {
            return 0;
        }
        let sign = if s.starts_with('-') { -1 } else { 1 };
        let (h, m) = (s[1..3].parse::<i64>().unwrap_or(0), s[3..5].parse::<i64>().unwrap_or(0));
        sign * (h * 3600 + m * 60)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(Default)]
    struct TestHub(Mutex<Vec<Event>>);
    impl Hub for TestHub {
        fn broadcast(&self, e: Event) {
            self.0.lock().unwrap().push(e);
        }
    }
    fn wait_for(h: &TestHub, f: impl Fn(&Event) -> bool) {
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        loop {
            if h.0.lock().unwrap().iter().any(&f) {
                return;
            }
            assert!(
                std::time::Instant::now() < deadline,
                "event missing: {:?}",
                h.0.lock().unwrap()
            );
            thread::sleep(Duration::from_millis(30));
        }
    }
    fn exercise(poll: bool) {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("root");
        std::fs::create_dir_all(root.join("nested")).unwrap();
        std::fs::create_dir_all(root.join("excluded")).unwrap();
        std::fs::write(root.join("nested/a.PNG"), b"a").unwrap();
        std::fs::write(root.join("nested/b.glb"), b"b").unwrap();
        std::fs::write(root.join("excluded/no.png"), b"x").unwrap();
        let hub = Arc::new(TestHub::default());
        let w = Watcher::new(
            vec![root.to_string_lossy().into_owned()],
            &WatcherOpts {
                interval: 0.1,
                exclude: vec!["excluded".into()],
                poll,
            },
            hub.clone(),
        );
        w.start();
        assert_eq!(w.len(), 2);
        std::fs::write(root.join("new.png"), b"new").unwrap();
        wait_for(
            &hub,
            |e| matches!(e,Event::Add { item } if item.name == "new.png"),
        );
        std::fs::write(root.join("nested/a.PNG"), b"changed").unwrap();
        wait_for(
            &hub,
            |e| matches!(e,Event::Update { item } if item.name == "a.PNG"),
        );
        std::fs::remove_file(root.join("new.png")).unwrap();
        wait_for(
            &hub,
            |e| matches!(e,Event::Remove { rel, .. } if rel == "new.png"),
        );
        let incoming = temp.path().join("incoming");
        std::fs::create_dir(&incoming).unwrap();
        std::fs::write(incoming.join("m.obj"), b"m").unwrap();
        std::fs::rename(incoming, root.join("incoming")).unwrap();
        wait_for(
            &hub,
            |e| matches!(e,Event::Add { item } if item.name == "m.obj"),
        );
        w.stop();
        let count = hub.0.lock().unwrap().len();
        std::fs::write(root.join("after.png"), b"x").unwrap();
        thread::sleep(Duration::from_millis(100));
        assert_eq!(count, hub.0.lock().unwrap().len());
    }
    #[test]
    fn watcher_polling() {
        exercise(true);
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn watcher_inotify() {
        exercise(false);
    }
}
