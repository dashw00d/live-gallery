#!/usr/bin/env node
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { SidecarApp } from 'sidecar_sdk';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverPyPath = path.join(__dirname, 'server.py');

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function waitForHealth(port, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(`http://127.0.0.1:${port}/healthz`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      });
      req.on('error', retry);
      req.setTimeout(500, () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) reject(new Error('Python backend failed to become healthy'));
      else setTimeout(attempt, 80);
    };
    attempt();
  });
}

let activePy = null;
let activePyPort = 0;
let shuttingDown = false;
let reloading = false;

async function startPythonBackend() {
  const pyPort = await getFreePort();
  const pyEnv = { ...process.env };
  delete pyEnv.ANTIGRAVITY_SIDECAR_WEB_PORT;
  delete pyEnv.PORT;

  const child = spawn('python3', [serverPyPath, '--port', String(pyPort)], {
    cwd: __dirname,
    env: pyEnv,
    stdio: 'inherit',
  });

  child.on('exit', (code) => {
    if (!shuttingDown && child === activePy) {
      console.error(`[live-gallery] Python backend exited with code ${code}; restarting backend...`);
      setTimeout(() => {
        if (!shuttingDown && child === activePy) {
          reloadBackend().catch((err) => console.error('[live-gallery] restart failed:', err.message));
        }
      }, 400);
    }
  });

  await waitForHealth(pyPort);
  return { child, pyPort };
}

async function reloadBackend() {
  if (reloading || shuttingDown) return false;
  reloading = true;
  try {
    const prev = activePy;
    const { child, pyPort } = await startPythonBackend();
    activePy = child;
    activePyPort = pyPort;
    console.log(`[live-gallery] hot-swapped python backend -> 127.0.0.1:${pyPort}`);
    if (prev && prev !== child) {
      setTimeout(() => {
        try { prev.kill('SIGTERM'); } catch {}
      }, 300);
    }
    return true;
  } finally {
    reloading = false;
  }
}

function cleanup() {
  if (shuttingDown) return;
  shuttingDown = true;
  try { activePy?.kill('SIGTERM'); } catch {}
}
process.on('SIGTERM', () => { cleanup(); process.exit(0); });
process.on('SIGINT', () => { cleanup(); process.exit(0); });
process.on('exit', cleanup);

// Initial boot
{
  const { child, pyPort } = await startPythonBackend();
  activePy = child;
  activePyPort = pyPort;
}

// Watch server.py for zero-downtime hot reload (never triggers Antigravity sidecar restart!)
let watchTimer = null;
try {
  fs.watch(__dirname, (_, filename) => {
    if (filename === 'server.py') {
      clearTimeout(watchTimer);
      watchTimer = setTimeout(() => {
        reloadBackend().catch((err) => console.error('[live-gallery] hot-reload failed:', err.message));
      }, 350);
    }
  });
} catch {}

const app = new SidecarApp();
const server = await app.run();
const origListeners = server.listeners('request');
server.removeAllListeners('request');

function isSdkRoute(urlStr) {
  const pathname = (urlStr || '/').split('?')[0];
  return pathname === '/preload.js' || pathname.startsWith('/_sidecar/');
}

server.on('request', (req, res) => {
  const reqUrl = req.url || '/';
  const pathname = reqUrl.split('?')[0];

  if (pathname === '/_lg/reload' && req.method === 'POST') {
    reloadBackend()
      .then((ok) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok, port: activePyPort }));
      })
      .catch((err) => {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: err.message }));
      });
    return;
  }

  if (isSdkRoute(reqUrl)) {
    for (const listener of origListeners) {
      listener.call(server, req, res);
    }
    return;
  }

  const targetPort = activePyPort;
  const headers = { ...req.headers, host: `127.0.0.1:${targetPort}`, connection: 'close' };
  delete headers['accept-encoding'];

  const proxyReq = http.request(
    {
      hostname: '127.0.0.1',
      port: targetPort,
      path: reqUrl,
      method: req.method,
      headers,
      agent: false,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res);
    }
  );

  proxyReq.on('error', (err) => {
    console.error(`[live-gallery proxy] ${req.method} ${reqUrl}: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'backend unavailable', detail: err.message }));
    } else {
      res.end();
    }
  });

  res.on('close', () => {
    if (!res.writableEnded) proxyReq.destroy();
  });

  if (req.method === 'GET' || req.method === 'HEAD') {
    proxyReq.end();
  } else {
    req.pipe(proxyReq);
  }
});

console.log(`[live-gallery] SidecarApp proxy ready -> python backend 127.0.0.1:${activePyPort}`);
