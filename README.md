# Windows TLS Intruder

A Frida-based tool for intercepting, inspecting, and modifying TLS and socket
traffic from running Windows processes — with a live web UI for forwarding,
editing, or dropping individual messages in real time.

The agent hooks into target processes at the library level: reads are captured
**post-decrypt**, writes are captured **pre-encrypt**. You see plaintext with
no network-level MITM, no CA certificate installation, and no proxy
configuration.

---

## Features

- **In-process hooks** — works on any process without modifying its binary or
  network configuration
- **Intercept & edit** — forward, drop, or modify any message before it
  reaches the network stack or the application
- **Live web UI** — real-time traffic log, hex dump viewer, inline hex editor
- **Process browser** — lists running processes with icons; click to attach
- **Spawn or attach** — start a new process under the hook, or attach to an
  already-running one
- **Child gating** — automatically hooks child processes spawned by the target
- **Multiple hook scripts** — select which TLS/socket libraries to hook per session
- **Auto-forward timeout** — intercepts self-resolve after a configurable
  timeout so a forgotten browser tab can't freeze the target

---

## Supported hooks

| Script | Library | Hooked functions |
|--------|---------|-----------------|
| **schannel** | `Secur32.dll` | `EncryptMessage`, `DecryptMessage` |
| **openssl** | `libssl*`, `ssleay*`, etc. | `SSL_write`, `SSL_write_ex`, `SSL_read`, `SSL_read_ex`, `SSL_shutdown` |
| **winsock** | `ws2_32.dll`, `wsock32.dll` | `send`, `sendto`, `recv`, `recvfrom`, `WSASend`, `WSASendTo`, `WSARecv`, `WSARecvFrom`, `closesocket`, `shutdown` |
| **gnutls** | `gnutls*` | `gnutls_record_send`, `gnutls_record_recv`, `gnutls_bye` |
| **libc** | `libc.so`, `libsocket.so`, `libpthread.so` | `send`, `sendto`, `recv`, `recvfrom`, `shutdown`, `close` |

Schannel covers most native Windows apps (.NET `HttpClient`, WinHTTP, Edge,
curl on Windows, etc.). OpenSSL covers Python, Node.js, and many bundled
libraries. All scripts are optional and can be mixed per session.

---

## Quick start

### Requirements

- Python 3.10+
- Node.js 18+ (only needed to build the UI; skip if using a pre-built
  `web/dist/`)
- Windows (Schannel and Winsock hooks are Windows-only; OpenSSL/GnuTLS/libc
  hooks work cross-platform)

### Install

```sh
pip install -e .
cd web
npm install
npm run build
cd ..
```

### Run

```sh
tls-intruder
# or
python -m intruder.app
```

Open **<http://127.0.0.1:8443>** in your browser.

### Configuration

All settings are environment variables with the `TLS_INTRUDER_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `TLS_INTRUDER_HOST` | `127.0.0.1` | Bind address |
| `TLS_INTRUDER_PORT` | `8443` | Bind port |
| `TLS_INTRUDER_AUTO_FORWARD_TIMEOUT_MS` | `30000` | Auto-forward a pending message after this many ms |
| `TLS_INTRUDER_MAX_PENDING` | `5000` | Max pending messages held in memory |
| `TLS_INTRUDER_DEBUG` | `false` | Verbose logging + write compiled agent to `frida_scripts/_debug_agent.js` |

---

## How it works

```
Target process (e.g. chrome.exe)
  │
  │  Frida injects JS agent
  ▼
┌──────────────────────────────┐
│  JS agent (in-process)       │
│  hooks TLS/socket functions  │
│  send(msg, data)             │  ← target thread blocks here
│  recv(id).wait()  ◄──────────┼──────────────────────────────────┐
└──────────────────────────────┘                                   │
                │ Frida IPC                                        │
                ▼                                                  │
┌──────────────────────────────┐                                   │
│  Python – MessageRouter      │                                   │
│  creates InterceptedMessage  │                                   │
│  → pending_store.enqueue()   │  blocks on threading.Event        │
└──────────┬───────────────────┘                                   │
           │ WebSocket broadcast                                   │
           ▼                                                       │
┌──────────────────────────────┐                                   │
│  React UI                    │                                   │
│  shows pending message       │                                   │
│  user clicks Forward/Edit/   │                                   │
│  Drop                        │                                   │
└──────────┬───────────────────┘                                   │
           │ POST /api/pending/{id}/resolve                        │
           ▼                                                       │
┌──────────────────────────────┐                                   │
│  PendingStore.resolve()      │                                   │
│  sets threading.Event        │──── script.post(resolved data) ───┘
└──────────────────────────────┘
```

The target thread is unblocked only after a resolution is received (or the
auto-forward timeout fires). The JS agent then writes the resolved bytes back
into the original buffer before the real function executes.

---

## Project layout

```
intruder/           Python backend (FastAPI + Frida session management)
  app.py            REST endpoints, WebSocket, static file serving
  session_manager.py  Frida spawn/attach/detach, child gating
  router.py         Frida message → InterceptedMessage, pending resolution
  pending.py        Thread-safe pending store with blocking wait
  ws_hub.py         WebSocket broadcast hub
  script_loader.py  Concatenates JS scripts into a single Frida agent
  models.py         Data classes and enums
  config.py         Pydantic settings
  processes.py      Process listing + Windows icon extraction

frida_scripts/      JavaScript hooks injected into target processes
  config.js         Empty config object (populated at load time)
  common.js         Shared helpers: intercept(), socket metadata, buffers
  openssl.js        OpenSSL SSL_read/write hooks
  schannel.js       Windows Schannel EncryptMessage/DecryptMessage hooks
  winsock.js        Winsock send/recv/WSASend/WSARecv hooks
  gnutls.js         GnuTLS record send/recv hooks
  libc.js           POSIX libc send/recv hooks

web/src/            React + TypeScript frontend
  App.tsx           Main UI: process browser, session panel, traffic log
  api.ts            Typed REST client
  useWs.ts          WebSocket hook with auto-reconnect
  hex.ts            Base64/hex encode-decode and hex dump formatter
```

---

## Security notes

- **Authorized use only.** This tool hooks arbitrary processes and reads their
  plaintext traffic. Only use it on systems you own or are explicitly
  authorized to test.
- The server binds to **localhost** by default. Do not change `TLS_INTRUDER_HOST`
  to a public interface without understanding the implications.
- Modifying data lengths in Schannel buffers can crash some applications.
  Prefer same-length replacements or "forward" when exploring unknown targets.

---

## License

MIT
