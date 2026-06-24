import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuoteCard } from "./QuoteCard";
import type { PriceResult } from "../types";

const quoteResult: PriceResult = {
  pricing: {
    annualPremium: 612.34,
    currency: "GBP",
    monthly: { deposit: 51.04, instalment: 51.03, instalments: 12 },
    outcome: "quote",
    reasons: [],
    breakdown: [
      { label: "Base premium", amount: 500 },
      { label: "Comprehensive cover", amount: 112.34 },
    ],
  },
  explanation: "Your annual premium is £612.34.",
};

const declineResult: PriceResult = {
  pricing: {
    outcome: "decline",
    reasons: ["Unspent criminal conviction", "Insurance previously voided"],
  },
  explanation: "Unfortunately we cannot offer cover for this quote because: ...",
};

describe("QuoteCard — quote", () => {
  it("renders premium, monthly and breakdown", () => {
    render(<QuoteCard result={quoteResult} onPurchase={vi.fn()} onIssuePolicy={vi.fn()} />);
    expect(screen.getByText(/612.34/)).toBeInTheDocument();
    expect(screen.getByText(/51.03 \/month/)).toBeInTheDocument();
    expect(screen.getByText(/Base premium/)).toBeInTheDocument();
    expect(screen.getByText(/Comprehensive cover/)).toBeInTheDocument();
  });

  it("shows the purchase link after Continue to purchase", async () => {
    const onPurchase = vi.fn().mockResolvedValue("https://acme.example/purchase/tok123");
    render(<QuoteCard result={quoteResult} onPurchase={onPurchase} onIssuePolicy={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Continue to purchase/i }));
    await waitFor(() => {
      const link = screen.getByRole("link", { name: /ACME checkout/i });
      expect(link).toHaveAttribute("href", "https://acme.example/purchase/tok123");
    });
    expect(onPurchase).toHaveBeenCalledOnce();
  });

  it("shows the policy number after Issue policy", async () => {
    const onIssuePolicy = vi.fn().mockResolvedValue({
      policyNumber: "ACME-POL-TEST",
      status: "ISSUED",
      effectiveDate: "2026-07-01",
    });
    render(<QuoteCard result={quoteResult} onPurchase={vi.fn()} onIssuePolicy={onIssuePolicy} />);
    fireEvent.click(screen.getByRole("button", { name: /Issue policy/i }));
    await waitFor(() => expect(screen.getByText(/ACME-POL-TEST/)).toBeInTheDocument());
    expect(screen.getByText(/ISSUED/)).toBeInTheDocument();
  });
});

describe("QuoteCard — decline", () => {
  it("renders the explanation and reasons, with no purchase button", () => {
    render(<QuoteCard result={declineResult} onPurchase={vi.fn()} onIssuePolicy={vi.fn()} />);
    expect(screen.getByText(/cannot offer cover/i)).toBeInTheDocument();
    expect(screen.getByText(/Unspent criminal conviction/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue to purchase/i })).toBeNull();
  });
});
