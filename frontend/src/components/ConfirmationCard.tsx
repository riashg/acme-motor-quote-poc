import type { Candidate } from "../types";

function str(v: unknown): string {
  return v === undefined || v === null ? "" : String(v);
}

function Row({ label, value }: { label: string; value: unknown }) {
  const text = str(value);
  if (!text) return null;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13, margin: "2px 0" }}>
      <span style={{ opacity: 0.6 }}>{label}</span>
      <strong>{text}</strong>
    </div>
  );
}

export function ConfirmationCard({
  candidate,
  onConfirm,
}: {
  candidate: Candidate;
  onConfirm: () => void;
}) {
  const v = candidate.vehicle ?? {};
  const d = candidate.driver ?? {};
  const isGB = candidate.cover_tier !== undefined || candidate.voluntary_excess !== undefined;

  return (
    <div
      style={{
        background: "var(--acme-card)",
        border: "1px solid #e0e0ef",
        borderLeft: "6px solid var(--acme-red)",
        borderRadius: 10,
        padding: 16,
        margin: "8px 0",
        maxWidth: 420,
      }}
    >
      <div style={{ color: "var(--acme-blue)", fontWeight: 700, marginBottom: 8 }}>
        Please confirm your details
      </div>

      <div style={{ fontSize: 12, fontWeight: 700, opacity: 0.5, margin: "8px 0 2px" }}>Vehicle</div>
      <Row label="Make" value={v.make} />
      <Row label="Model" value={v.model} />
      <Row label="Year" value={v.year} />
      <Row label="Identifier" value={v.identifier} />
      <Row label="Value" value={v.value} />
      <Row label="Insurance group" value={v.insurance_group} />

      <div style={{ fontSize: 12, fontWeight: 700, opacity: 0.5, margin: "8px 0 2px" }}>Driver</div>
      <Row label="Name" value={d.full_name} />
      <Row label="Date of birth" value={d.date_of_birth} />
      {isGB ? (
        <>
          <Row label="Postcode" value={d.postcode} />
          <Row label="No-claims years" value={d.ncb_years} />
        </>
      ) : (
        <>
          <Row label="Code postal" value={d.code_postal} />
          <Row label="Bonus-malus" value={d.bonus_malus} />
        </>
      )}

      <div style={{ fontSize: 12, fontWeight: 700, opacity: 0.5, margin: "8px 0 2px" }}>Cover</div>
      {isGB ? (
        <>
          <Row label="Cover tier" value={candidate.cover_tier} />
          <Row label="Voluntary excess" value={candidate.voluntary_excess} />
        </>
      ) : (
        <>
          <Row label="Formule" value={candidate.formule} />
          <Row label="Franchise" value={candidate.franchise} />
        </>
      )}

      <div style={{ fontSize: 12, opacity: 0.6, margin: "10px 0" }}>
        Please check these are accurate before we price your quote.
      </div>

      <button
        onClick={onConfirm}
        style={{
          background: "var(--acme-blue)",
          color: "#fff",
          border: 0,
          borderRadius: 8,
          padding: "10px 18px",
          fontWeight: 700,
        }}
      >
        Confirm &amp; get my quote
      </button>
    </div>
  );
}
