import { useRef, useState } from "react";
import { confirmQuote, streamChat, uploadDocument } from "../api";
import type { Candidate } from "../types";
import { Composer } from "./Composer";
import { type ChatItem, MessageList } from "./MessageList";

export function ChatWindow() {
  const [items, setItems] = useState<ChatItem[]>([
    { role: "assistant", text: "Hi! I'm your ACME motor assistant. Tell me about your car to get a quote." },
  ]);
  const sessionId = useRef(crypto.randomUUID()).current;
  const candidate = useRef<Candidate | null>(null);

  async function send(msg: string) {
    setItems((p) => [...p, { role: "user", text: msg }]);
    await streamChat(sessionId, msg, (e) => {
      if (e.type === "text") {
        setItems((p) => [...p, { role: "assistant", text: e.data as string }]);
      }
      if (e.type === "confirm") {
        const c = e.data as Candidate;
        candidate.current = c;
        setItems((p) => [...p, { role: "assistant", candidate: c }]);
      }
    });
  }

  async function upload(file: File) {
    setItems((p) => [...p, { role: "user", text: `📎 Uploaded ${file.name}` }]);
    const res = await uploadDocument(sessionId, file);
    const names = Object.keys(res.fields).join(", ");
    setItems((p) => [
      ...p,
      {
        role: "assistant",
        text: `I read these from your ${res.country_code} document: ${names}. Anything to add or correct?`,
      },
    ]);
  }

  async function onConfirm() {
    const result = await confirmQuote(sessionId);
    candidate.current = null;
    setItems((p) => [...p, { role: "assistant", result }]);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div className="acme-header">ACME <span className="acme-accent">Motor</span> — quote assistant (demo)</div>
      <MessageList items={items} onConfirm={onConfirm} />
      <Composer onSend={send} onUpload={upload} />
    </div>
  );
}
