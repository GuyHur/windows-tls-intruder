import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PendingMsg, type ProcessInfo, type SessionInfo } from "./api";
import { useWs, type WsEvent } from "./useWs";
import { b64ToBytes, bytesToB64, hexDump, parseHex } from "./hex";

interface LogEntry extends PendingMsg {
  status: "pending" | "resolved";
  action?: string;
}

export function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const [tab, setTab] = useState<"traffic" | "pending">("traffic");
  const [sidebarTab, setSidebarTab] = useState<"session" | "processes">("processes");

  const onWs = useCallback((ev: WsEvent) => {
    if (ev.type === "pending") {
      const msg = ev.message as PendingMsg;
      const entry: LogEntry = { ...msg, status: "pending" };
      setLog((prev) => [entry, ...prev]);
    }
    if (ev.type === "resolved") {
      setLog((prev) =>
        prev.map((e) =>
          e.id === ev.id ? { ...e, status: "resolved", action: ev.action as string } : e,
        ),
      );
    }
    if (ev.type === "session_created") {
      setSessions((prev) => [...prev, ev.session as SessionInfo]);
    }
    if (ev.type === "session_destroyed") {
      setSessions((prev) => prev.filter((s) => s.id !== ev.session_id));
    }
  }, []);

  const { connected } = useWs(onWs);

  useEffect(() => {
    api.sessions().then((r) => setSessions(r.sessions));
    api.pending().then((r) =>
      setLog(r.pending.map((m) => ({ ...m, status: "pending" as const }))),
    );
  }, []);

  const [mode, setMode] = useState<"spawn" | "attach">("attach");
  const [target, setTarget] = useState("");
  const [availableScripts, setAvailableScripts] = useState<string[]>([]);
  const [selectedScripts, setSelectedScripts] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.scripts().then((r) => {
      setAvailableScripts(r.scripts);
      setSelectedScripts(new Set(r.scripts));
    });
  }, []);

  const toggleScript = (s: string) =>
    setSelectedScripts((prev) => {
      const next = new Set(prev);
      next.has(s) ? next.delete(s) : next.add(s);
      return next;
    });

  const startSession = async () => {
    if (!target.trim()) return;
    const scripts = [...selectedScripts];
    try {
      if (mode === "spawn") await api.spawn(target.trim(), scripts);
      else await api.attach(target.trim(), scripts);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const attachToProcess = async (proc: ProcessInfo) => {
    const scripts = [...selectedScripts];
    try {
      await api.attach(proc.pid, scripts);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const deleteSession = async (id: string) => {
    try {
      await api.deleteSession(id);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const pendingItems = log.filter((e) => e.status === "pending");

  return (
    <div className="app">
      <div className="topbar">
        <h1>TLS Intruder</h1>
        <div className={`dot ${connected ? "dot-on" : "dot-off"}`} title={connected ? "Connected" : "Disconnected"} />
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
          {sessions.length} session{sessions.length !== 1 && "s"}
        </span>
      </div>

      <div className="panels">
        <div className="sidebar">
          <div className="sidebar-tabs">
            <div
              className={`sidebar-tab ${sidebarTab === "processes" ? "active" : ""}`}
              onClick={() => setSidebarTab("processes")}
            >
              Processes
            </div>
            <div
              className={`sidebar-tab ${sidebarTab === "session" ? "active" : ""}`}
              onClick={() => setSidebarTab("session")}
            >
              Session
            </div>
          </div>

          {sidebarTab === "processes" && (
            <ProcessBrowser
              onAttach={attachToProcess}
              availableScripts={availableScripts}
              selectedScripts={selectedScripts}
              toggleScript={toggleScript}
            />
          )}

          {sidebarTab === "session" && (
            <>
              <section>
                <h2>Manual attach / spawn</h2>
                <div className="field">
                  <label>Mode</label>
                  <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
                    <option value="attach">Attach (PID / name)</option>
                    <option value="spawn">Spawn (exe path)</option>
                  </select>
                </div>
                <div className="field">
                  <label>{mode === "spawn" ? "Executable path" : "PID or process name"}</label>
                  <input
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                    placeholder={mode === "spawn" ? "C:\\app.exe" : "1234 or app.exe"}
                    onKeyDown={(e) => e.key === "Enter" && startSession()}
                  />
                </div>
                <div className="field">
                  <label>Hook scripts</label>
                  {availableScripts.map((s) => (
                    <label key={s} className="check-row">
                      <input type="checkbox" checked={selectedScripts.has(s)} onChange={() => toggleScript(s)} />
                      {s}
                    </label>
                  ))}
                </div>
                <button className="btn btn-primary" style={{ width: "100%" }} onClick={startSession}>
                  {mode === "spawn" ? "Spawn & Hook" : "Attach & Hook"}
                </button>
              </section>

              <section>
                <h2>Active sessions</h2>
                {sessions.length === 0 && <p style={{ fontSize: 12, color: "var(--text-dim)" }}>No active sessions</p>}
                {sessions.map((s) => (
                  <div key={s.id} className="session-card">
                    <div className="top">
                      <span className="target">{s.target}</span>
                      <button className="btn btn-sm btn-danger" onClick={() => deleteSession(s.id)}>Detach</button>
                    </div>
                    <div className="meta">
                      PIDs: {s.pids.join(", ")} &middot; {s.scripts.join(", ")}
                    </div>
                  </div>
                ))}
              </section>
            </>
          )}
        </div>

        <div className="main">
          <div className="tabs">
            <div className={`tab ${tab === "traffic" ? "active" : ""}`} onClick={() => setTab("traffic")}>
              Traffic ({log.length})
            </div>
            <div className={`tab ${tab === "pending" ? "active" : ""}`} onClick={() => setTab("pending")}>
              Pending ({pendingItems.length})
            </div>
          </div>

          <div className="tab-body">
            <TrafficTable
              items={tab === "pending" ? pendingItems : log}
              selected={selected}
              onSelect={setSelected}
            />
          </div>

          {selected && (
            <DetailPane entry={selected} onResolved={() => setSelected(null)} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Process browser ──────────────────────────────────────────────────

function ProcessBrowser({
  onAttach,
  availableScripts,
  selectedScripts,
  toggleScript,
}: {
  onAttach: (proc: ProcessInfo) => void;
  availableScripts: string[];
  selectedScripts: Set<string>;
  toggleScript: (s: string) => void;
}) {
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.processes();
      setProcesses(r.processes);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const q = search.toLowerCase();
  const filtered = processes.filter(
    (p) =>
      p.name.toLowerCase().includes(q) ||
      p.exe.toLowerCase().includes(q) ||
      String(p.pid).includes(q),
  );

  return (
    <div className="process-browser">
      <section>
        <h2>Hook scripts</h2>
        <div className="script-chips">
          {availableScripts.map((s) => (
            <label key={s} className="check-row">
              <input type="checkbox" checked={selectedScripts.has(s)} onChange={() => toggleScript(s)} />
              {s}
            </label>
          ))}
        </div>
      </section>

      <section className="process-section">
        <div className="process-header">
          <h2>Running processes</h2>
          <button className="btn btn-sm" onClick={refresh} disabled={loading}>
            {loading ? "…" : "↻"}
          </button>
        </div>
        <input
          className="process-search"
          placeholder="Search by name, path or PID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="process-list">
          {filtered.map((p) => (
            <ProcessRow key={p.pid} proc={p} onAttach={onAttach} />
          ))}
          {filtered.length === 0 && !loading && (
            <p style={{ fontSize: 12, color: "var(--text-dim)", padding: 12 }}>
              {processes.length === 0 ? "Loading…" : "No matching processes"}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function ProcessRow({ proc, onAttach }: { proc: ProcessInfo; onAttach: (p: ProcessInfo) => void }) {
  const [imgFailed, setImgFailed] = useState(false);

  const initial = (proc.name || "?")[0].toUpperCase();

  return (
    <div className="process-row" onClick={() => onAttach(proc)} title={proc.exe || proc.name}>
      <div className="process-icon-wrap">
        {!imgFailed && proc.exe ? (
          <img
            className="process-icon"
            src={api.processIconUrl(proc.pid)}
            alt=""
            loading="lazy"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <div className="process-icon-fallback">{initial}</div>
        )}
      </div>
      <div className="process-info">
        <span className="process-name">{proc.name}</span>
        <span className="process-meta">PID {proc.pid}</span>
      </div>
    </div>
  );
}

// ── Traffic table ────────────────────────────────────────────────────

function TrafficTable({
  items,
  selected,
  onSelect,
}: {
  items: LogEntry[];
  selected: LogEntry | null;
  onSelect: (e: LogEntry) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  return (
    <>
      <table className="traffic">
        <thead>
          <tr>
            <th>Dir</th>
            <th>Size</th>
            <th>Module</th>
            <th>PID</th>
            <th>Status</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr
              key={e.id}
              onClick={() => onSelect(e)}
              style={{ cursor: "pointer", background: selected?.id === e.id ? "#ffffff0a" : undefined }}
            >
              <td className={e.direction === "send" ? "dir-send" : "dir-recv"}>
                {e.direction === "send" ? "→ SEND" : "← RECV"}
              </td>
              <td>{e.data_len} B</td>
              <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                {(e.metadata?.m as string) ?? "—"}
              </td>
              <td>{e.pid}</td>
              <td>
                <span className={`badge ${e.status === "pending" ? "badge-pending" : "badge-resolved"}`}>
                  {e.status === "resolved" ? e.action : "pending"}
                </span>
              </td>
              <td style={{ fontSize: 12, color: "var(--text-dim)" }}>
                {new Date(e.created_at * 1000).toLocaleTimeString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div ref={bottomRef} />
    </>
  );
}

// ── Detail / hex editor pane ─────────────────────────────────────────

function DetailPane({ entry, onResolved }: { entry: LogEntry; onResolved: () => void }) {
  const bytes = b64ToBytes(entry.data_b64);
  const [editing, setEditing] = useState(false);
  const [hexText, setHexText] = useState("");

  const startEdit = () => {
    setHexText(
      Array.from(bytes)
        .map((b) => b.toString(16).padStart(2, "0"))
        .join(" "),
    );
    setEditing(true);
  };

  const resolve = async (action: "forward" | "replace" | "drop") => {
    let data_b64: string | undefined;
    if (action === "replace") {
      const edited = parseHex(hexText);
      data_b64 = bytesToB64(edited);
    }
    try {
      await api.resolve(entry.id, action, data_b64);
      setEditing(false);
      onResolved();
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="detail-pane">
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
          {entry.direction.toUpperCase()} &middot; {bytes.length} bytes &middot; {entry.id}
        </span>
      </div>

      {!editing && <pre className="hex-dump">{hexDump(bytes)}</pre>}

      {editing && (
        <textarea
          className="hex-edit"
          value={hexText}
          onChange={(e) => setHexText(e.target.value)}
          spellCheck={false}
        />
      )}

      {entry.status === "pending" && (
        <div className="action-bar">
          {!editing && (
            <>
              <button className="btn btn-sm" onClick={() => resolve("forward")}>Forward</button>
              <button className="btn btn-sm" onClick={startEdit}>Edit</button>
              <button className="btn btn-sm btn-danger" onClick={() => resolve("drop")}>Drop</button>
            </>
          )}
          {editing && (
            <>
              <button className="btn btn-sm btn-primary" onClick={() => resolve("replace")}>
                Send edited
              </button>
              <button className="btn btn-sm" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
