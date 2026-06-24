import type { Conflict, PolicyResult, PriceResult } from "../types";
import { ConflictPrompt } from "./ConflictPrompt";
import { QuoteCard } from "./QuoteCard";

export interface ChatItem {
  kind: "text" | "echo" | "conflict" | "quote";
  role?: "user" | "assistant";
  text?: string;
  conflict?: Conflict;
  resolved?: boolean;
  result?: PriceResult;
}

export function MessageList({
  items,
  readyToPrice,
  pricing,
  onGetQuote,
  onResolve,
  onPurchase,
  onIssuePolicy,
}: {
  items: ChatItem[];
  readyToPrice: boolean;
  pricing: boolean;
  onGetQuote: () => void;
  onResolve: (path: string, value: unknown) => void;
  onPurchase: () => Promise<string>;
  onIssuePolicy: () => Promise<PolicyResult>;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
      {items.map((it, i) => {
        if (it.kind === "echo") {
          return (
            <div key={i} style={{ fontSize: 12, opacity: 0.55, margin: "2px 4px" }}>
              {it.text}
            </div>
          );
        }
        if (it.kind === "conflict" && it.conflict) {
          return (
            <ConflictPrompt
              key={i}
              conflict={it.conflict}
              onResolve={onResolve}
              resolved={it.resolved}
            />
          );
        }
        if (it.kind === "quote" && it.result) {
          return (
            <QuoteCard
              key={i}
              result={it.result}
              onPurchase={onPurchase}
              onIssuePolicy={onIssuePolicy}
            />
          );
        }
        // text bubble
        return (
          <div key={i} style={{ textAlign: it.role === "user" ? "right" : "left" }}>
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
          </div>
        );
      })}

      {readyToPrice && (
        <div style={{ margin: "12px 0" }}>
          <button
            onClick={onGetQuote}
            disabled={pricing}
            style={{
              background: "var(--acme-red)",
              color: "#fff",
              border: 0,
              borderRadius: 8,
              padding: "12px 22px",
              fontWeight: 700,
              fontSize: 15,
            }}
          >
            {pricing ? "Pricing…" : "Get my quote"}
          </button>
        </div>
      )}
    </div>
  );
}
