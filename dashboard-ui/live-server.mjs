#!/usr/bin/env node
// live-server.mjs - opt-in, explicitly user-started local server that keeps the team
// dashboard current without manual `npm run dashboard`/`/dashboard` reruns.
//
// This is ADDITIVE, not a replacement: `/dashboard`, `npm run dashboard` (the single-file
// static build), and the Artifact preview all stay exactly as they are today - this project's
// deliberate "static build, zero server, no port, no auth surface" default (ADR-013) is
// untouched. This script is the opt-in alternative, same relationship `npm run dev`/
// `npm run preview` already have to that default: present, useful, never auto-run by anything
// else (confirmed via AskUserQuestion 2026-08-09 - the user explicitly wants a real persistent
// server, not just easier manual regeneration).
//
// Design (see the plan this was built from for the full rationale):
// - Full-page reload on rebuild, not fine-grained data patching. The React app's data flow is
//   completely untouched - it still statically imports dashboard-data.json at build time.
//   "Live" means: poll -> regenerate -> rebuild the whole dist/index.html -> tell the browser
//   to reload. Zero risk to the existing static build, since none of that code changes.
// - Polling, not fs.watch. fs.watch's recursive flag has real cross-platform gaps (notably
//   historically on Linux), and this project already cares a lot about inconsistent
//   corporate-Windows environments (see install_helper.py's own PATH-detection lengths).
//   Every POLL_SECONDS, re-run the existing `npm run data` (cheap - a Python stdlib scan,
//   already fast across dozens of projects per this session's own usage), hash the resulting
//   JSON, and only rebuild + notify when the hash actually changed. The staleness window is
//   the poll interval, not instant - stated plainly in every log line, never oversold as
//   event-driven.
// - No new dependencies: Node built-ins only (http, fs, crypto, child_process).
// - Bind address defaults to 127.0.0.1, matching this session's own `vite preview` precedent
//   and the house rule's "no auth surface" spirit - real project/cost data sits behind this.
//   --host 0.0.0.0 opts into LAN exposure explicitly, with the same plain warning used earlier
//   tonight for the one-off `vite preview --host` case.

import { createServer } from 'node:http'
import { createHash } from 'node:crypto'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST_DIR = path.join(__dirname, 'dist')
const DATA_FILE = path.join(__dirname, 'data', 'dashboard-data.json')

function parseArgs(argv) {
  const opts = { port: 4174, host: '127.0.0.1', pollSeconds: 8 }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--port') opts.port = Number(argv[++i])
    else if (a === '--host') opts.host = argv[++i]
    else if (a === '--poll-seconds') opts.pollSeconds = Number(argv[++i])
    else if (a === '--help' || a === '-h') opts.help = true
  }
  return opts
}

const args = parseArgs(process.argv.slice(2))
if (args.help) {
  console.log(
    'Usage: node live-server.mjs [--port 4174] [--host 127.0.0.1] [--poll-seconds 8]\n\n' +
      'Opt-in, live-updating local dashboard server. See dashboard-ui/README.md.',
  )
  process.exit(0)
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
}

// The live-reload snippet is injected only into what THIS server serves, at serve time - the
// dist/index.html file on disk (and everything /dashboard, npm run dashboard, and the Artifact
// extraction produce) stays byte-for-byte unchanged, never carrying this script.
const LIVE_RELOAD_SNIPPET = `
<script>
  (function () {
    console.info('[dashboard:live] connecting for live updates...')
    var es = new EventSource('/events')
    es.addEventListener('reload', function () {
      console.info('[dashboard:live] data changed - reloading')
      location.reload()
    })
    es.onerror = function () {
      console.info('[dashboard:live] live-update connection lost (server stopped?)')
    }
  })()
</script>
`

function run(cmd, cmdArgs, opts = {}) {
  return spawnSync(cmd, cmdArgs, {
    cwd: __dirname,
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...opts,
  })
}

function runQuiet(cmd, cmdArgs, opts = {}) {
  return spawnSync(cmd, cmdArgs, {
    cwd: __dirname,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: process.platform === 'win32',
    ...opts,
  })
}

function npmCmd() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

// Hashes the MEANINGFUL content of dashboard-data.json, not the raw bytes: emit_json() stamps
// a `generated` timestamp (minute resolution) on every single scan regardless of whether any
// real project/engagement data actually changed, which made a byte-hash rebuild on every poll
// cycle even with nothing new to show (caught live during this script's own first manual test
// run - real bug, not hypothetical). Excluding just that one field is enough: everything else
// in the payload is real, observed data.
function hashFile(p) {
  if (!existsSync(p)) return null
  let data
  try {
    data = JSON.parse(readFileSync(p, 'utf-8'))
  } catch {
    return null // unparseable - treat as "unknown", never crash the poll loop over it
  }
  if (data && typeof data === 'object') delete data.generated
  return createHash('sha256').update(JSON.stringify(data)).digest('hex')
}

function log(msg) {
  const ts = new Date().toISOString().slice(11, 19)
  console.log(`[dashboard:live ${ts}] ${msg}`)
}

// ---- initial build (full pipeline, once) ----
log('building the dashboard for the first time (npm run dashboard)...')
const initial = run(npmCmd(), ['run', 'dashboard'])
if (initial.status !== 0) {
  console.error('[dashboard:live] initial build failed - fix the error above and try again.')
  process.exit(1)
}
let lastHash = hashFile(DATA_FILE)

// ---- SSE clients ----
const sseClients = new Set()

function broadcastReload() {
  for (const res of sseClients) {
    try {
      res.write('event: reload\ndata: {}\n\n')
    } catch {
      sseClients.delete(res)
    }
  }
}

// ---- poll loop: regenerate data, rebuild + notify only on real change ----
function pollOnce() {
  const dataResult = runQuiet(npmCmd(), ['run', 'data'])
  if (dataResult.status !== 0) {
    log('data regeneration failed this cycle - keeping the last good build (see stderr below)')
    if (dataResult.stderr) process.stderr.write(dataResult.stderr)
    return
  }
  const newHash = hashFile(DATA_FILE)
  if (newHash === lastHash) return // nothing real changed - no rebuild, no reload
  log('real project/engagement data changed - rebuilding...')
  // vite build only (no tsc -b): source code hasn't changed, only the data has, and
  // tsconfig.app.json's noEmit:true means tsc -b is a typecheck gate, not something vite
  // build's output depends on - skipping it here is a real speedup, not a shortcut that risks
  // shipping broken code (the initial build above already ran the full typechecked pipeline).
  const buildResult = runQuiet('npx', ['vite', 'build'])
  if (buildResult.status !== 0) {
    log('rebuild failed - keeping the previous dist/index.html (see stderr below)')
    if (buildResult.stderr) process.stderr.write(buildResult.stderr)
    return
  }
  lastHash = newHash
  log(`rebuilt - notifying ${sseClients.size} connected tab(s)`)
  broadcastReload()
}

setInterval(pollOnce, Math.max(1, args.pollSeconds) * 1000)

// ---- static file server ----
function safeResolve(urlPath) {
  const decoded = decodeURIComponent(urlPath.split('?')[0])
  const rel = decoded === '/' ? '/index.html' : decoded
  const resolved = path.normalize(path.join(DIST_DIR, rel))
  // Path-traversal guard: the resolved path must stay under DIST_DIR.
  if (!resolved.startsWith(DIST_DIR + path.sep) && resolved !== DIST_DIR) return null
  return resolved
}

const server = createServer((req, res) => {
  if (req.url === '/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    })
    res.write('\n')
    sseClients.add(res)
    req.on('close', () => sseClients.delete(res))
    return
  }

  const resolved = safeResolve(req.url || '/')
  if (!resolved || !existsSync(resolved) || !statSync(resolved).isFile()) {
    res.writeHead(404, { 'Content-Type': 'text/plain' })
    res.end('Not found')
    return
  }
  const ext = path.extname(resolved)
  const contentType = MIME[ext] || 'application/octet-stream'
  if (ext === '.html') {
    let html = readFileSync(resolved, 'utf-8')
    html = html.replace('</body>', LIVE_RELOAD_SNIPPET + '</body>')
    res.writeHead(200, { 'Content-Type': contentType })
    res.end(html)
    return
  }
  res.writeHead(200, { 'Content-Type': contentType })
  res.end(readFileSync(resolved))
})

server.listen(args.port, args.host, () => {
  const url = `http://${args.host}:${args.port}/`
  log(`serving ${url}`)
  log(`polling every ${args.pollSeconds}s for real data changes - not instant, this is by design (see README)`)
  if (args.host !== '127.0.0.1' && args.host !== 'localhost') {
    log(`WARNING: bound to ${args.host} - reachable by anything that can reach this host, not just this machine. Your real project/cost data is behind this URL.`)
  }
  log('Ctrl-C to stop.')
})
