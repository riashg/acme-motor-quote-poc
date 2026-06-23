import type { ChatEvent, ConfirmResult, UploadResult } from "./types";

// Same-origin by default (the backend serves the built UI). In local dev,
// set VITE_API_BASE=http://localhost:8000 (see .env.development).
const BASE = import.meta.env.VITE_API_BASE ?? "";

export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!resp.ok) {
    throw new Error(`Chat request failed: HTTP ${resp.status}`);
  }

  // Stream incrementally when supported, with a full-read fallback for
  // browsers that don't expose a readable response body (e.g. some Safari).
  const emitFrame = (frame: string) => {
    const line = frame.replace(/^data: /, "").trim();
    if (line) onEvent(JSON.parse(line) as ChatEvent);
  };

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

  // Fallback: read the whole response and parse all SSE frames at once.
  const text = await resp.text();
  for (const frame of text.split("\n\n")) emitFrame(frame);
}

export async function uploadDocument(
  sessionId: string,
  file: File,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("file", file);
  const resp = await fetch(`${BASE}/upload`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) throw new Error(`Upload failed: HTTP ${resp.status}`);
  return (await resp.json()) as UploadResult;
}

export async function confirmQuote(sessionId: string): Promise<ConfirmResult> {
  const resp = await fetch(`${BASE}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!resp.ok) throw new Error(`Confirm failed: HTTP ${resp.status}`);
  return (await resp.json()) as ConfirmResult;
}
