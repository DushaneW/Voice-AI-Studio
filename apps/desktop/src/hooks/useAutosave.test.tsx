// @vitest-environment jsdom
import {act,cleanup,renderHook} from "@testing-library/react";
import {afterEach,expect,it,vi} from "vitest";
import {useAutosave} from "./useAutosave";
afterEach(() => {cleanup(); vi.useRealTimers();});
it("saves latest content and respects busy or recovery state",async () => {
 vi.useFakeTimers(); const first=vi.fn().mockResolvedValue(true),latest=vi.fn().mockResolvedValue(true);
 const {result,rerender}=renderHook(({busy,save})=>useAutosave(true,busy,save,5),{initialProps:{busy:true,save:first}});
 await act(async()=>{await vi.advanceTimersByTimeAsync(6000);}); expect(first).not.toHaveBeenCalled();
 rerender({busy:false,save:first}); rerender({busy:false,save:latest});
 await act(async()=>{await vi.advanceTimersByTimeAsync(5000);}); expect(latest).toHaveBeenCalledTimes(1); expect(result.current.savedAt).not.toBeNull();
});
it("pauses failed autosave despite busy state transitions until explicit resume",async()=>{
 vi.useFakeTimers(); let finish!:(ok:boolean)=>void;
 const save=vi.fn(()=>new Promise<boolean>(resolve=>{finish=resolve;}));
 const {result,rerender}=renderHook(({busy})=>useAutosave(true,busy,save,5),{initialProps:{busy:false}});
 await act(async()=>{await vi.advanceTimersByTimeAsync(5000);}); rerender({busy:true});
 await act(async()=>{finish(false);}); rerender({busy:false}); expect(result.current.failed).toBe(true);
 await act(async()=>{await vi.advanceTimersByTimeAsync(60000);}); expect(save).toHaveBeenCalledTimes(1);
 act(()=>result.current.resume()); await act(async()=>{await vi.advanceTimersByTimeAsync(5000);}); expect(save).toHaveBeenCalledTimes(2);
});
it("never saves clean documents or disabled autosave",async()=>{
 vi.useFakeTimers(); const save=vi.fn(); renderHook(()=>useAutosave(false,false,save,5)); renderHook(()=>useAutosave(true,false,save,0));
 await act(async()=>{await vi.advanceTimersByTimeAsync(60000);}); expect(save).not.toHaveBeenCalled();
});
