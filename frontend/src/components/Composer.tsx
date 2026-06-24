import { useRef, useState } from "react";

// Composer: text input + a 📎 button that STAGES a file as a removable chip (it
// does NOT send on select). Send submits text + any staged file together
// (brief §17.5). Send is enabled when there's text OR a staged file.
export function Composer({
  onSend,
  disabled,
}: {
  onSend: (message: string, file: File | null) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [staged, setStaged] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const canSend = !disabled && (text.trim().length > 0 || staged !== null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    onSend(text.trim(), staged);
    setText("");
    setStaged(null);
  }

  return (
    <form
      onSubmit={submit}
      style={{ padding: 12, borderTop: "1px solid #ddd", display: "flex", flexDirection: "column", gap: 8 }}
    >
      {staged && (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            alignSelf: "flex-start",
            background: "#eef",
            border: "1px solid #ccd",
            borderRadius: 16,
            padding: "4px 10px",
            fontSize: 13,
          }}
        >
          📎 {staged.name}
          <button
            type="button"
            aria-label="Remove attachment"
            onClick={() => setStaged(null)}
            style={{ background: "transparent", border: 0, fontSize: 16, lineHeight: 1 }}
          >
            ×
          </button>
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          ref={fileRef}
          type="file"
          accept="image/*,application/pdf"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) setStaged(file);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          aria-label="Attach document"
          title="Attach a document"
          onClick={() => fileRef.current?.click()}
          style={{ background: "#fff", border: "1px solid #ccc", borderRadius: 8, padding: "0 12px", fontSize: 18 }}
        >
          📎
        </button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            staged
              ? "Add a note for this document (optional), then Send"
              : "e.g. I drive AB12CDE, I'm 34, 5 years no-claims, SW1A 1AA"
          }
          style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid #ccc" }}
        />
        <button
          type="submit"
          disabled={!canSend}
          style={{
            background: canSend ? "var(--acme-blue)" : "#aab",
            color: "#fff",
            border: 0,
            borderRadius: 8,
            padding: "0 16px",
          }}
        >
          Send
        </button>
      </div>
    </form>
  );
}
