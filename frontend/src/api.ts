import type {
  ChatEvent,
  PolicyResult,
  PriceResult,
  PurchaseResult,
  StartResult,
  UploadResult,
} from "./types";

// Same-origin by default (the backend serves the built UI). In local dev,
// set VITE_API_BASE=http://localhost:8000 (see .env.development).
const BASE = import.meta.env.VITE_API_BASE ?? "";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = new Error(`${path} failed: HTTP ${resp.status}`) as Error & {
      status?: number;
      body?: unknown;
    };
    err.status = resp.status;
    try {
      err.body = await resp.json();
    } catch {
      /* ignore */
    }
    throw err;
  }
  return (await resp.json()) as T;
}

// POST /start — begin a quote. The backend generates and returns the
// session_id (see main.py); all later calls must use that returned id.
export function start(): Promise<StartResult> {
  return postJson<StartResult>("/start", {});
}

// POST /chat — one greedy turn, streamed as SSE (echo/text/conflict/done).
export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  await streamSse("/chat", { session_id: sessionId, message }, onEvent);
}

// POST /resolve — apply a conflict resolution, streamed as SSE.
export async function resolve(
  sessionId: string,
  path: string,
  value: unknown,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  await streamSse("/resolve", { session_id: sessionId, path, value }, onEvent);
}

async function streamSse(
  path: string,
  body: unknown,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const resp = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`${path} failed: HTTP ${resp.status}`);
  }

  const emitFrame = (frame: string) => {
    const line = frame.replace(/^data: /, "").trim();
    if (line) onEvent(JSON.parse(line) as ChatEvent);
  };

  // Stream incrementally when supported, with a full-read fallback for
  // browsers that don't expose a readable response body (e.g. some Safari).
  if (resp.body && typeof resp.body.getReader === "function") {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) emitFrame(part);
    }
    if (buffer.trim()) emitFrame(buffer);
    return;
  }

  const text = await resp.text();
  for (const frame of text.split("\n\n")) emitFrame(frame);
}

// POST /upload — multipart document-assisted extraction.
export async function uploadDocument(
  sessionId: string,
  file: File,
  message: string,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("file", file);
  form.append("message", message);
  const resp = await fetch(`${BASE}/upload`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`Upload failed: HTTP ${resp.status}`);
  return (await resp.json()) as UploadResult;
}

// POST /price — price the quote. Resolves with the {pricing, explanation} on a
// priced quote; rejects with a status-tagged error (422 carries missingFields).
export function price(sessionId: string): Promise<PriceResult> {
  return postJson<PriceResult>("/price", { session_id: sessionId });
}

// POST /purchase — generate a purchase link for a clean quote.
export function purchase(sessionId: string): Promise<PurchaseResult> {
  return postJson<PurchaseResult>("/purchase", { session_id: sessionId });
}

// POST /issue-policy — issue a (mock) policy for a clean quote.
export function issuePolicy(sessionId: string): Promise<PolicyResult> {
  return postJson<PolicyResult>("/issue-policy", { session_id: sessionId });
}
