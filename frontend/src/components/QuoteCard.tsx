import type { ConfirmResult } from "../types";

export function QuoteCard({ result }: { result: ConfirmResult }) {
  const { quote, handoff_url } = result;
  return (
    <div
      style={{
        background: "var(--acme-card)",
        border: "1px solid #e0e0ef",
        borderLeft: "6px solid var(--acme-blue)",
        borderRadius: 10,
        padding: 16,
        margin: "8px 0",
        maxWidth: 420,
      }}
    >
      <div style={{ color: "var(--acme-blue)", fontWeight: 700 }}>ACME Motor Quote</div>
      <div style={{ fontSize: 13, opacity: 0.7 }}>
        Ref {quote.quote_ref} · {quote.country_code}
      </div>
      <div style={{ fontSize: 32, fontWeight: 800, margin: "8px 0" }}>
        {quote.currency}
        {quote.annual_premium.toFixed(2)}
        <span style={{ fontSize: 14, fontWeight: 400 }}> /year</span>
      </div>
      <div className="acme-accent">
        {quote.currency}
        {quote.monthly_premium.toFixed(2)} /month
      </div>
      <a
        href={handoff_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: "inline-block",
          marginTop: 14,
          background: "var(--acme-blue)",
          color: "#fff",
          textDecoration: "none",
          fontWeight: 700,
          padding: "10px 18px",
          borderRadius: 8,
        }}
      >
        Continue to ACME →
      </a>
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 12 }}>
        Illustrative demo — mock data only, not a real or binding ACME quote.
      </div>
    </div>
  );
}
