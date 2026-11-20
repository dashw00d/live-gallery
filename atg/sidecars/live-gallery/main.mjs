#!/usr/bin/env node
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { SidecarApp } from 'sidecar_sdk';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

function waitForHealth(port, timeoutMs = 5000) {
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

const pyPort = await getFreePort();
const pyEnv = { ...process.env };
delete pyEnv.ANTIGRAVITY_SIDECAR_WEB_PORT;
delete pyEnv.PORT;

const py = spawn('python3', [path.join(__dirname, 'server.py'), '--port', String(pyPort)], {
  cwd: __dirname,
  env: pyEnv,
  stdio: 'inherit',
});

let shuttingDown = false;
function cleanup() {
  if (shuttingDown) return;
  shuttingDown = true;
  try { py.kill('SIGTERM'); } catch {}
}
process.on('SIGTERM', () => { cleanup(); process.exit(0); });
process.on('SIGINT', () => { cleanup(); process.exit(0); });
process.on('exit', cleanup);
py.on('exit', (code) => {
  if (!shuttingDown) {
    console.error(`[live-gallery] Python backend exited with code ${code}`);
    process.exit(code || 1);
  }
});

await waitForHealth(pyPort);

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
  if (isSdkRoute(reqUrl)) {
    for (const listener of origListeners) {
      listener.call(server, req, res);
    }
    return;
  }

  // Transparent streaming proxy to the local Python Live Gallery backend
  const headers = { ...req.headers, host: `127.0.0.1:${pyPort}`, connection: 'close' };
  delete headers['accept-encoding'];

  const proxyReq = http.request(
    {
      hostname: '127.0.0.1',
      port: pyPort,
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

console.log(`[live-gallery] SidecarApp proxy ready -> python backend 127.0.0.1:${pyPort}`);
