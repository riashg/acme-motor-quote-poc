import type { Candidate, ConfirmResult } from "../types";
import { ConfirmationCard } from "./ConfirmationCard";
import { QuoteCard } from "./QuoteCard";

export interface ChatItem {
  role: "user" | "assistant";
  text?: string;
  candidate?: Candidate;
  result?: ConfirmResult;
}

export function MessageList({
  items,
  onConfirm,
}: {
  items: ChatItem[];
  onConfirm: () => void;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
      {items.map((it, i) => (
        <div key={i} style={{ textAlign: it.role === "user" ? "right" : "left" }}>
          {it.text && (
            <div
              style={{
                display: "inline-block",
                background: it.role === "user" ? "var(--acme-blue)" : "#eee",
                color: it.role === "user" ? "#fff" : "#000",
                padding: "8px 12px",
                borderRadius: 12,
                margin: "4px 0",
                maxWidth: "80%",
              }}
            >
              {it.text}
            </div>
          )}
          {it.candidate && <ConfirmationCard candidate={it.candidate} onConfirm={onConfirm} />}
          {it.result && <QuoteCard result={it.result} />}
        </div>
      ))}
    </div>
  );
}
