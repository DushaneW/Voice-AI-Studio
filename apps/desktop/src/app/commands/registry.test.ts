import { describe, expect, it } from "vitest";
import { shortcutMatches } from "./registry";
const event = (values: Partial<KeyboardEvent>) =>
  ({
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    key: "k",
    ...values,
  }) as KeyboardEvent;
describe("cross-platform shortcuts", () => {
  it("accepts control or command", () => {
    expect(shortcutMatches(event({ ctrlKey: true }), "mod+k")).toBe(true);
    expect(shortcutMatches(event({ metaKey: true }), "mod+k")).toBe(true);
  });
  it("rejects extra modifiers and plain typing", () => {
    expect(shortcutMatches(event({}), "mod+k")).toBe(false);
    expect(
      shortcutMatches(event({ ctrlKey: true, shiftKey: true }), "mod+k"),
    ).toBe(false);
    expect(
      shortcutMatches(event({ ctrlKey: true, altKey: true }), "mod+k"),
    ).toBe(false);
  });
});
