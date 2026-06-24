import { useEffect, useRef, useState } from "react";
import {
  issuePolicy,
  price,
  purchase,
  resolve,
  start,
  streamChat,
  uploadDocument,
} from "../api";
import type { ChatEvent, JourneyState } from "../types";
import { Composer } from "./Composer";
import { type ChatItem, MessageList } from "./MessageList";

const READY: JourneyState[] = ["ready_to_price", "quoted", "policy_issued"];

export function ChatWindow() {
  // The backend's /start issues the session_id every later call must use.
  const sessionId = useRef<string>("");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [journey, setJourney] = useState<JourneyState>("collecting");
  const [started, setStarted] = useState(false);
  const [pricing, setPricing] = useState(false);
  const [priced, setPriced] = useState(false);

  const append = (item: ChatItem) => setItems((p) => [...p, item]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await start();
        if (cancelled) return;
        sessionId.current = res.session_id;
        setJourney(res.journeyState);
        setStarted(true);
        append({
          kind: "text",
          role: "assistant",
          text: "Hi! I'm your ACME motor assistant. Tell me about your car and yourself, or attach a document, to get a quote.",
        });
      } catch {
        append({
          kind: "text",
          role: "assistant",
          text: "Sorry — I couldn't start a session. Is the backend running?",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function handleEvent(e: ChatEvent) {
    if (e.type === "echo") {
      if (e.data) append({ kind: "echo", text: e.data });
    } else if (e.type === "text") {
      append({ kind: "text", role: "assistant", text: e.data });
    } else if (e.type === "conflict") {
      append({ kind: "conflict", conflict: e.data });
    }
  }

  async function onSend(message: string, file: File | null) {
    if (file) {
      append({
        kind: "text",
        role: "user",
        text: message ? `📎 ${file.name} — ${message}` : `📎 ${file.name}`,
      });
      try {
        const res = await uploadDocument(sessionId.current, file, message);
        if (res.echo) append({ kind: "echo", text: res.echo });
        if (res.extracted.length) {
          append({
            kind: "text",
            role: "assistant",
            text: `I read these from your document: ${res.extracted.join(", ")}.`,
          });
        }
        for (const c of res.conflicts) append({ kind: "conflict", conflict: c });
        if (res.journeyState) setJourney(res.journeyState);
        if (!res.conflicts.length && !READY.includes(res.journeyState ?? "")) {
          append({
            kind: "text",
            role: "assistant",
            text: "Got it — anything else to add or correct?",
          });
        }
      } catch {
        append({ kind: "text", role: "assistant", text: "Sorry — I couldn't read that document." });
      }
      return;
    }

    if (!message) return;
    append({ kind: "text", role: "user", text: message });
    try {
      await streamChat(sessionId.current, message, handleEvent);
      await refreshJourney();
    } catch {
      append({ kind: "text", role: "assistant", text: "Sorry — something went wrong. Please try again." });
    }
  }

  // The SSE turn doesn't carry journey state; the agent says "ready to be
  // priced" on completion. Detect readiness by attempting a quiet flag flip.
  async function refreshJourney() {
    // The backend tells us "ready_to_price" via the closing text; mark ready
    // when the last assistant text announces it (keeps the contract simple).
    setItems((p) => {
      const lastText = [...p].reverse().find((it) => it.kind === "text" && it.role === "assistant");
      if (lastText?.text?.includes("ready to be priced")) {
        setJourney("ready_to_price");
      }
      return p;
    });
  }

  async function onResolve(path: string, value: unknown) {
    setItems((p) =>
      p.map((it) =>
        it.kind === "conflict" && it.conflict?.path === path ? { ...it, resolved: true } : it,
      ),
    );
    try {
      await resolve(sessionId.current, path, value, handleEvent);
      await refreshJourney();
    } catch {
      append({ kind: "text", role: "assistant", text: "Sorry — I couldn't apply that. Please try again." });
    }
  }

  async function onGetQuote() {
    setPricing(true);
    try {
      const res = await price(sessionId.current);
      append({ kind: "quote", result: res });
      setJourney(res.pricing.outcome === "quote" ? "quoted" : res.pricing.outcome);
      setPriced(true);
    } catch (err) {
      const e = err as { status?: number; body?: { missingFields?: string[] } };
      if (e.status === 422 && e.body?.missingFields) {
        append({
          kind: "text",
          role: "assistant",
          text: `I still need a few details before I can price this: ${e.body.missingFields.join(", ")}.`,
        });
        setJourney("collecting");
      } else {
        append({ kind: "text", role: "assistant", text: "Sorry — I couldn't price the quote." });
      }
    } finally {
      setPricing(false);
    }
  }

  async function onPurchase() {
    const res = await purchase(sessionId.current);
    return res.purchaseUrl;
  }

  async function onIssuePolicy() {
    return issuePolicy(sessionId.current);
  }

  const readyToPrice = started && !priced && READY.includes(journey);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div className="acme-header">
        ACME <span className="acme-accent">Motor</span> — quote assistant (demo)
      </div>
      <MessageList
        items={items}
        readyToPrice={readyToPrice}
        pricing={pricing}
        onGetQuote={onGetQuote}
        onResolve={onResolve}
        onPurchase={onPurchase}
        onIssuePolicy={onIssuePolicy}
      />
      <Composer onSend={onSend} disabled={!started} />
    </div>
  );
}
