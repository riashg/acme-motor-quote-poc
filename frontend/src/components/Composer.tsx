import { useRef, useState } from "react";

export function Composer({
  onSend,
  onUpload,
}: {
  onSend: (msg: string) => void;
  onUpload: (file: File) => void;
}) {
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) {
          onSend(text.trim());
          setText("");
        }
      }}
      style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid #ddd" }}
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/*,application/pdf"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onUpload(file);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        aria-label="Upload document"
        title="Upload a document"
        onClick={() => fileRef.current?.click()}
        style={{
          background: "#fff",
          border: "1px solid #ccc",
          borderRadius: 8,
          padding: "0 12px",
          fontSize: 18,
        }}
      >
        📎
      </button>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. I drive AB12CDE, age 34, 5 years NCB, SW1A 1AA"
        style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid #ccc" }}
      />
      <button style={{ background: "var(--acme-blue)", color: "#fff", border: 0, borderRadius: 8, padding: "0 16px" }}>
        Send
      </button>
    </form>
  );
}
