import { useState } from "react";
import type { Conflict } from "../types";

const chipStyle: React.CSSProperties = {
  background: "#fff",
  border: "1px solid var(--acme-blue)",
  color: "var(--acme-blue)",
  borderRadius: 16,
  padding: "6px 14px",
  fontSize: 13,
  fontWeight: 600,
};

function display(v: unknown): string {
  return v === null || v === undefined ? "(none)" : String(v);
}

// A conflict prompt (brief §4.6): two quick chips (current vs proposed) plus a
// free-text option, all resolving via onResolve(path, value).
export function ConflictPrompt({
  conflict,
  onResolve,
  resolved,
}: {
  conflict: Conflict;
  onResolve: (path: string, value: unknown) => void;
  resolved?: boolean;
}) {
  const [freeText, setFreeText] = useState("");

  return (
    <div
      style={{
        background: "var(--acme-card)",
        border: "1px solid #e0e0ef",
        borderLeft: "6px solid var(--acme-red)",
        borderRadius: 10,
        padding: 14,
        margin: "8px 0",
        maxWidth: 460,
      }}
    >
      <div style={{ fontSize: 14, marginBottom: 10 }}>{conflict.message}</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button
          style={chipStyle}
          disabled={resolved}
          onClick={() => onResolve(conflict.path, conflict.current)}
        >
          Keep {display(conflict.current)}
        </button>
        <button
          style={chipStyle}
          disabled={resolved}
          onClick={() => onResolve(conflict.path, conflict.proposed)}
        >
          Use {display(conflict.proposed)}
        </button>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (freeText.trim()) onResolve(conflict.path, freeText.trim());
        }}
        style={{ display: "flex", gap: 8, marginTop: 10 }}
      >
        <input
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder="…or type the correct value"
          disabled={resolved}
          style={{ flex: 1, padding: 8, borderRadius: 8, border: "1px solid #ccc" }}
        />
        <button style={chipStyle} disabled={resolved || !freeText.trim()}>
          Set
        </button>
      </form>
    </div>
  );
}
