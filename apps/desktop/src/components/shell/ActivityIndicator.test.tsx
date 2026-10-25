// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ActivityIndicator, activeProgress } from "./ActivityIndicator";
import { translator } from "../../app/i18n";
import type { Job } from "../../types/domain";

afterEach(cleanup);
const t = translator("en");
const job = (state: Job["state"], progress: number | null = null) =>
  ({ id: state + progress, state, progress, kind: "tts" }) as unknown as Job;

it("renders nothing while no job is queued or running", () => {
  const { container } = render(
    <ActivityIndicator jobs={[job("completed")]} t={t} onOpen={() => {}} />,
  );
  expect(container.innerHTML).toBe("");
});

it("counts active jobs, shows mean progress and opens the jobs page", () => {
  const onOpen = vi.fn();
  render(
    <ActivityIndicator
      jobs={[job("running", 0.2), job("running", 0.6), job("queued")]}
      t={t}
      onOpen={onOpen}
    />,
  );
  const button = screen.getByRole("button");
  expect(button.textContent).toBe("3");
  expect(button.className).toContain("is-running");
  expect(button.getAttribute("title")).toBe("Running: 2 · Queued: 1 · 40%");
  fireEvent.click(button);
  expect(onOpen).toHaveBeenCalledOnce();
});

it("only averages running jobs that report progress", () => {
  expect(activeProgress([job("running"), job("queued", 0.9)])).toBeNull();
  expect(activeProgress([job("running", 1), job("running")])).toBe(1);
});
