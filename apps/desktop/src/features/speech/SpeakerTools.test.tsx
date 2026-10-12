// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SpeakerTools } from "./SpeakerTools";
import { translator } from "../../app/i18n";
afterEach(cleanup);
it("requires explicit merge confirmation and keeps segment timing and text", () => {
  const change = vi.fn();
  const segments = [
    { start: 0, end: 1, text: "Hello", speaker: "Alice" },
    { start: 1, end: 2, text: "Hi", speaker: "Bob" },
  ];
  render(
    <SpeakerTools
      segments={segments}
      disabled={false}
      t={translator("en")}
      onChange={change}
    />,
  );
  fireEvent.change(screen.getByLabelText("Existing speaker"), {
    target: { value: "Alice" },
  });
  fireEvent.change(screen.getByLabelText("New or target speaker name"), {
    target: { value: "Bob" },
  });
  const button = screen.getByText("Merge speakers") as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  expect(change).toHaveBeenCalledWith([
    { ...segments[0], speaker: "Bob" },
    segments[1],
  ]);
  expect(segments[0].speaker).toBe("Alice");
});
