import { useState } from "react";
import type { PolicyResult, PriceResult } from "../types";

function money(currency: string | undefined, amount: number | undefined): string {
  const symbol = currency === "GBP" || !currency ? "£" : `${currency} `;
  if (amount === undefined || amount === null) return "";
  const n = Number(amount);
  return n === Math.trunc(n) ? `${symbol}${n}` : `${symbol}${n.toFixed(2)}`;
}

const cardStyle = (accent: string): React.CSSProperties => ({
  background: "var(--acme-card)",
  border: "1px solid #e0e0ef",
  borderLeft: `6px solid ${accent}`,
  borderRadius: 10,
  padding: 16,
  margin: "8px 0",
  maxWidth: 460,
});

const primaryButton: React.CSSProperties = {
  background: "var(--acme-blue)",
  color: "#fff",
  border: 0,
  borderRadius: 8,
  padding: "10px 18px",
  fontWeight: 700,
};

export function QuoteCard({
  result,
  onPurchase,
  onIssuePolicy,
}: {
  result: PriceResult;
  onPurchase: () => Promise<string>;
  onIssuePolicy: () => Promise<PolicyResult>;
}) {
  const { pricing, explanation } = result;
  const [purchaseUrl, setPurchaseUrl] = useState<string | null>(null);
  const [policy, setPolicy] = useState<PolicyResult | null>(null);
  const [busy, setBusy] = useState<"purchase" | "policy" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (pricing.outcome !== "quote") {
    const accent = "var(--acme-red)";
    return (
      <div style={cardStyle(accent)}>
        <div style={{ color: "var(--acme-blue)", fontWeight: 700 }}>
          {pricing.outcome === "refer" ? "Referred to an adviser" : "We can't offer cover"}
        </div>
        <div style={{ fontSize: 14, margin: "8px 0" }}>{explanation}</div>
        {pricing.reasons && pricing.reasons.length > 0 && (
          <ul style={{ margin: "8px 0", paddingLeft: 18, fontSize: 13 }}>
            {pricing.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 12 }}>
          Illustrative demo — mock data only, not a real or binding ACME quote.
        </div>
      </div>
    );
  }

  async function doPurchase() {
    setBusy("purchase");
    setError(null);
    try {
      setPurchaseUrl(await onPurchase());
    } catch {
      setError("Couldn't generate a purchase link.");
    } finally {
      setBusy(null);
    }
  }

  async function doIssuePolicy() {
    setBusy("policy");
    setError(null);
    try {
      setPolicy(await onIssuePolicy());
    } catch {
      setError("Couldn't issue the policy.");
    } finally {
      setBusy(null);
    }
  }

  const monthly = pricing.monthly;

  return (
    <div style={cardStyle("var(--acme-blue)")}>
      <div style={{ color: "var(--acme-blue)", fontWeight: 700 }}>ACME Motor Quote</div>
      <div style={{ fontSize: 32, fontWeight: 800, margin: "8px 0" }}>
        {money(pricing.currency, pricing.annualPremium)}
        <span style={{ fontSize: 14, fontWeight: 400 }}> /year</span>
      </div>
      {monthly && monthly.instalment !== undefined && (
        <div className="acme-accent">
          {money(pricing.currency, monthly.instalment)} /month over {monthly.instalments}{" "}
          instalments
        </div>
      )}

      {pricing.breakdown && pricing.breakdown.length > 0 && (
        <div style={{ margin: "12px 0" }}>
          <div style={{ fontSize: 12, fontWeight: 700, opacity: 0.5, marginBottom: 4 }}>
            Breakdown
          </div>
          {pricing.breakdown.map((line, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 13,
                margin: "2px 0",
              }}
            >
              <span style={{ opacity: 0.7 }}>{line.label}</span>
              <strong>{money(pricing.currency, line.amount)}</strong>
            </div>
          ))}
        </div>
      )}

      {error && <div style={{ color: "var(--acme-red)", fontSize: 13 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
        {!purchaseUrl && (
          <button style={primaryButton} disabled={busy !== null} onClick={doPurchase}>
            {busy === "purchase" ? "Working…" : "Continue to purchase"}
          </button>
        )}
        {!policy && (
          <button
            style={{ ...primaryButton, background: "#fff", color: "var(--acme-blue)", border: "1px solid var(--acme-blue)" }}
            disabled={busy !== null}
            onClick={doIssuePolicy}
          >
            {busy === "policy" ? "Working…" : "Issue policy"}
          </button>
        )}
      </div>

      {purchaseUrl && (
        <div style={{ marginTop: 12 }}>
          <a
            href={purchaseUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ ...primaryButton, display: "inline-block", textDecoration: "none" }}
          >
            Go to ACME checkout →
          </a>
        </div>
      )}

      {policy && (
        <div style={{ marginTop: 12, fontSize: 14 }}>
          <div>
            Policy <strong>{policy.policyNumber}</strong> — {policy.status}
          </div>
          <div style={{ opacity: 0.7 }}>Effective {policy.effectiveDate}</div>
        </div>
      )}

      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 12 }}>
        Illustrative demo — mock data only, not a real or binding ACME quote.
      </div>
    </div>
  );
}
