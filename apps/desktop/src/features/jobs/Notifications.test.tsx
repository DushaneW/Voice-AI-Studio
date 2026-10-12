// @vitest-environment jsdom
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {Notifications} from "./Notifications";
import {JobEvents} from "./JobEvents";
import {request} from "../../services/runtime";
import {translator} from "../../app/i18n";
vi.mock("../../services/runtime", () => ({request: vi.fn()}));
HTMLDialogElement.prototype.showModal = function() {this.setAttribute("open", "");};
HTMLDialogElement.prototype.close = function() {this.removeAttribute("open");};
afterEach(() => {cleanup(); vi.resetAllMocks();});
it("acknowledges persisted notification and opens its exact job", async () => {
  const open = vi.fn();
  let read = 0;
  vi.mocked(request).mockImplementation(async (_method, path) => {
    if (path.endsWith("/read")) {read = 1; return {read: true};}
    return {items: [{id: 7, job_id: "old-job-outside-list", state: "completed", kind: "analyze", created: "2026-10-08", read}], next_cursor: null, unread: 1 - read};
  });
  render(<Notifications ready t={translator("en")} onOpenJob={open}/>);
  fireEvent.click(await screen.findByRole("button", {name: "Notifications (1)"}));
  fireEvent.click(screen.getByRole("button", {name: "Mark as read"}));
  await screen.findByRole("button", {name: "Notifications (0)"});
  expect(request).toHaveBeenCalledWith("POST", "/v1/notifications/7/read");
  fireEvent.click(screen.getByRole("button", {name: "Open job"}));
  expect(open).toHaveBeenCalledWith("old-job-outside-list");
});
it("loads durable history and retries the selected job", async () => {
  const action = vi.fn();
  vi.mocked(request).mockResolvedValue({job: {id: "failed-job", state: "failed", progress: null, updated: "2026-10-08"}, items: [{id: 2, state: "failed", error: "processing_failed", created: "2026-10-08"}], next_cursor: 2});
  render(<JobEvents id="failed-job" t={translator("en")} onAction={action}/>);
  fireEvent.click(await screen.findByRole("button", {name: "Retry"}));
  expect(action).toHaveBeenCalledWith("failed-job", "retry");
  fireEvent.click(screen.getByRole("button", {name: "Older entries"}));
  await waitFor(() => expect(request).toHaveBeenCalledWith("POST", "/v1/jobs/failed-job/events", {before: 2}));
});
