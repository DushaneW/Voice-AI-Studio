import { describe, expect, it } from "vitest";
import { isWorkspaceEnabled, visibleWorkspace } from "./features";

describe("experimental workspaces", () => {
  it("are hidden by default and fall back to home", () => {
    for (const id of ["workflows", "audiobook", "dubbing"] as const) {
      expect(isWorkspaceEnabled(id, false)).toBe(false);
      expect(visibleWorkspace(id, false)).toBe("home");
    }
  });

  it("keep core workspaces visible", () => {
    for (const id of [
      "tts",
      "transcription",
      "timeline",
      "models",
      "jobs",
    ] as const) {
      expect(visibleWorkspace(id, false)).toBe(id);
    }
  });

  it("can be re-enabled by the experimental flag", () => {
    expect(visibleWorkspace("workflows", true)).toBe("workflows");
  });
});
