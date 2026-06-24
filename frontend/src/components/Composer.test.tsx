import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("enables Send when there's text and sends message + null file", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const send = screen.getByRole("button", { name: /^Send$/ }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/no-claims/i), {
      target: { value: "I drive AB12CDE" },
    });
    expect(send.disabled).toBe(false);

    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith("I drive AB12CDE", null);
  });

  it("stages a file as a removable chip without sending, and Send submits both", () => {
    const onSend = vi.fn();
    const { container } = render(<Composer onSend={onSend} />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["x"], "licence.png", { type: "image/png" });

    fireEvent.change(fileInput, { target: { files: [file] } });
    // Selecting a file does NOT send.
    expect(onSend).not.toHaveBeenCalled();
    // Chip shows the filename and Send is now enabled (file staged, no text).
    expect(screen.getByText(/licence.png/)).toBeInTheDocument();
    const send = screen.getByRole("button", { name: /^Send$/ }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);

    fireEvent.change(screen.getByPlaceholderText(/document/i), {
      target: { value: "this is my licence" },
    });
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith("this is my licence", file);
  });
});
