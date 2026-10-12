// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Jobs } from "./Jobs";
import { translator } from "../../app/i18n";
import { request } from "../../services/runtime";
import type { Job } from "../../types/domain";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("archives completed jobs and restores them without deleting files", async () => {
  const job = {
    id: "done",
    project_id: "project",
    asset_id: null,
    state: "completed",
    progress: 1,
    error: null,
    created: "today",
    kind: "tts",
    result: {
      asset_id: "audio",
      duration: 2,
      sample_rate: 24000,
      voice: "voice",
      model: "model",
    },
  } as Job;
  const changed = vi.fn();
  const error = vi.fn();
  vi.mocked(request).mockImplementation(async (method) =>
    method === "GET" ? [job] : {},
  );
  render(
    <Jobs
      jobs={[job]}
      assets={[]}
      onAction={vi.fn()}
      onChanged={changed}
      onError={error}
      t={translator("en")}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Archive completed jobs" }),
  );
  await screen.findByRole("button", { name: "Restore archived jobs" });
  expect(request).toHaveBeenCalledWith("POST", "/v1/jobs/archive");
  fireEvent.click(
    screen.getByRole("button", { name: "Restore archived jobs" }),
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("POST", "/v1/jobs/archive/restore"),
  );
  expect(changed).toHaveBeenCalledTimes(2);
  expect(error).not.toHaveBeenCalled();
});
it("opens an independently copied project and displays integrity findings", () => {
  const open = vi.fn();
  const base = {
    id: "copy",
    project_id: "source",
    asset_id: null,
    state: "completed",
    progress: 1,
    error: null,
    created: "2026-10-08",
  };
  const jobs = [
    {
      ...base,
      kind: "duplicate_project",
      result: { project_id: "target", copied_assets: 2 },
    },
    {
      ...base,
      id: "check",
      kind: "validate_project",
      result: {
        checked_assets: 2,
        checked_documents: 1,
        checked_transcripts: 0,
        issue_count: 1,
        omitted_issues: 0,
        issues: [{ kind: "asset", id: "missing-id", code: "asset_missing" }],
        started: "today",
        finished: "today",
      },
    },
  ] as Job[];
  render(
    <Jobs
      jobs={jobs}
      assets={[]}
      onAction={vi.fn()}
      onChanged={vi.fn()}
      onError={vi.fn()}
      onOpenProject={open}
      t={translator("en")}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Open project" }));
  expect(open).toHaveBeenCalledWith("target");
  fireEvent.click(screen.getAllByRole("button", { name: "Open" })[1]);
  expect(
    screen.getByRole("region", { name: "Integrity check results" }).textContent,
  ).toContain("asset_missing");
});
it("requires explicit repair action after displaying planned source revisions",async()=>{
 const changed=vi.fn();vi.mocked(request).mockResolvedValue({});
 const job={id:"plan",project_id:"project",asset_id:null,state:"completed",progress:1,error:null,created:"2026-10-11",kind:"plan_repair",result:{actions:[{category:"document",id:"project",expected_revision:4,source_revision:3}],unresolved:[],limited:false,history_limit:100,checked:1}} as Job;
 render(<Jobs jobs={[job]} assets={[]} onAction={vi.fn()} onChanged={changed} onError={vi.fn()} t={translator("en")}/>);
 fireEvent.click(screen.getByRole("button",{name:"Open"}));
 expect(screen.getByText(/4 → 3/)).toBeTruthy();
 expect(vi.mocked(request).mock.calls.some(c=>c[1].endsWith("apply-repair"))).toBe(false);
 fireEvent.click(screen.getByRole("button",{name:"Restore listed revisions"}));
 await waitFor(()=>expect(request).toHaveBeenCalledWith("POST","/v1/jobs/plan/apply-repair",{confirmed:true}));
 expect(changed).toHaveBeenCalled();
});
