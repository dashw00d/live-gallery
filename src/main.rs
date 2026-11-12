mod app;
mod events;
mod item;
mod server;
mod util;
mod watcher;
use clap::Parser;
use watcher::WatcherOpts;
#[derive(Parser)]
#[command(about = "Live, recursive gallery of new images and 3D models.")]
struct Args {
    /// Folders to watch (default: the last folder picked in the page, else --default, else the current folder)
    dirs: Vec<String>,
    /// Folder to watch when no DIR is given and none was picked yet
    #[arg(long)]
    default: Option<String>,
    /// Port (default 8765, or the next free one)
    #[arg(short, long)]
    port: Option<u16>,
    /// Seconds between scans when polling
    #[arg(short, long, default_value_t = 1.0)]
    interval: f64,
    /// Files per page: the newest N load first, older ones as you scroll
    #[arg(short = 'n', long, default_value_t = 60)]
    initial: usize,
    /// Folder name to skip (repeatable)
    #[arg(short = 'x', long)]
    exclude: Vec<String>,
    /// Poll instead of using inotify
    #[arg(long)]
    poll: bool,
    #[arg(long, default_value = "127.0.0.1")]
    host: String,
    /// Open the browser
    #[arg(long)]
    open: bool,
}
fn main() {
    let a = Args::parse();
    let app = app::App::new(
        WatcherOpts {
            interval: a.interval,
            exclude: a.exclude,
            poll: a.poll,
        },
        a.initial,
    );
    let roots = if !a.dirs.is_empty() {
        let (r, b) = util::norm_roots(&a.dirs);
        if !b.is_empty() {
            eprintln!("not a directory: {}", b.join(", "));
            std::process::exit(1)
        }
        r
    } else {
        let r = util::norm_roots(&app.saved_roots()).0;
        if r.is_empty() {
            let p = a.default.as_deref().unwrap_or(".");
            let r = util::norm_roots(&[p.to_string()]).0;
            if r.is_empty() {
                eprintln!("not a directory: {p}");
                std::process::exit(1)
            }
            r
        } else {
            r
        }
    };
    app.set_roots(roots, false);
    std::thread::spawn(|| util::prune_thumbs(6000, 9000));
    let ports: Vec<u16> = a
        .port
        .map(|p| vec![p])
        .unwrap_or_else(|| (8765..8785).collect());
    let listener = ports
        .into_iter()
        .find_map(|p| std::net::TcpListener::bind((a.host.as_str(), p)).ok())
        .unwrap_or_else(|| {
            eprintln!(
                "port unavailable: {}",
                a.port
                    .map(|p| p.to_string())
                    .unwrap_or_else(|| "8765-8784".into())
            );
            std::process::exit(1)
        });
    let port = listener.local_addr().unwrap().port();
    let host = if a.host == "127.0.0.1" || a.host == "0.0.0.0" {
        "localhost"
    } else {
        &a.host
    };
    let url = format!("http://{host}:{port}/");
    println!("Live Gallery: {url}   (change folders in the page; Ctrl+C to stop)");
    if a.open {
        let _ = open::that(&url);
    }
    listener.set_nonblocking(true).expect("set nonblocking");
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("runtime");
    rt.block_on(async { let listener=tokio::net::TcpListener::from_std(listener).expect("listener"); tokio::select! { result=server::serve(app,listener) => {if let Err(e)=result {eprintln!("server: {e}");}}, _=tokio::signal::ctrl_c() => {println!();} } });
}
