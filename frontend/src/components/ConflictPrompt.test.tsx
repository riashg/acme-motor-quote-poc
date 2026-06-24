import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConflictPrompt } from "./ConflictPrompt";
import type { Conflict } from "../types";

const conflict: Conflict = {
  path: "customer.surname",
  current: "Smith",
  proposed: "Smyth",
  chips: ["Smith", "Smyth"],
  message: 'I already have Surname as "Smith" but you\'ve said "Smyth". Which is correct?',
};

describe("ConflictPrompt", () => {
  it("renders both chips and resolves with the chosen value", () => {
    const onResolve = vi.fn();
    render(<ConflictPrompt conflict={conflict} onResolve={onResolve} />);
    fireEvent.click(screen.getByRole("button", { name: /Use Smyth/ }));
    expect(onResolve).toHaveBeenCalledWith("customer.surname", "Smyth");
  });

  it("resolves with free text", () => {
    const onResolve = vi.fn();
    render(<ConflictPrompt conflict={conflict} onResolve={onResolve} />);
    fireEvent.change(screen.getByPlaceholderText(/correct value/i), {
      target: { value: "Smithe" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Set$/ }));
    expect(onResolve).toHaveBeenCalledWith("customer.surname", "Smithe");
  });
});
