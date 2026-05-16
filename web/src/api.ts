const BASE = "";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export interface SessionInfo {
  id: string;
  target: string;
  pids: number[];
  scripts: string[];
  created_at: number;
}

export interface PendingMsg {
  id: string;
  session_id: string;
  pid: number;
  direction: "send" | "recv";
  data_b64: string;
  data_len: number;
  metadata: Record<string, unknown>;
  created_at: number;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  exe: string;
  username: string;
}

export const api = {
  health: () => json<{ status: string }>("/api/health"),
  scripts: () => json<{ scripts: string[] }>("/api/scripts"),
  sessions: () => json<{ sessions: SessionInfo[] }>("/api/sessions"),
  processes: () => json<{ processes: ProcessInfo[] }>("/api/processes"),
  processIconUrl: (pid: number) => `${BASE}/api/processes/${pid}/icon`,
  spawn: (path: string, scripts?: string[]) =>
    json<SessionInfo>("/api/sessions/spawn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, scripts }),
    }),
  attach: (target: string | number, scripts?: string[]) =>
    json<SessionInfo>("/api/sessions/attach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, scripts }),
    }),
  deleteSession: (id: string) =>
    json<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  pending: () => json<{ pending: PendingMsg[] }>("/api/pending"),
  resolve: (id: string, action: "forward" | "replace" | "drop", data_b64?: string) =>
    json<{ ok: boolean }>(`/api/pending/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, data_b64 }),
    }),
  getIntercept: () => json<{ enabled: boolean }>("/api/intercept"),
  setIntercept: (enabled: boolean) =>
    json<{ enabled: boolean }>("/api/intercept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
};
