import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QuoteCard } from "./QuoteCard";
import type { ConfirmResult } from "../types";

const result: ConfirmResult = {
  quote: {
    quote_ref: "ACME-GB-12345",
    currency: "£",
    annual_premium: 612.34,
    monthly_premium: 51.03,
    country_code: "GB",
    input: {},
  },
  handoff_url: "https://acme.example/checkout?guid=abc-123",
  guid: "abc-123",
};

describe("QuoteCard", () => {
  it("renders the premium, currency and quote ref", () => {
    render(<QuoteCard result={result} />);
    expect(screen.getByText(/612.34/)).toBeInTheDocument();
    expect(screen.getByText(/51.03/)).toBeInTheDocument();
    expect(screen.getAllByText(/£/).length).toBeGreaterThan(0);
    expect(screen.getByText(/ACME-GB-12345/)).toBeInTheDocument();
  });

  it("links the continue button at the handoff_url", () => {
    render(<QuoteCard result={result} />);
    const link = screen.getByRole("link", { name: /Continue to ACME/i });
    expect(link).toHaveAttribute("href", result.handoff_url);
    expect(link).toHaveAttribute("target", "_blank");
  });
});
