// @vitest-environment jsdom
import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,expect,it,vi} from "vitest";
import {SafetyCenter} from "./SafetyCenter";
import {request} from "../../services/runtime";
import {translator} from "../../app/i18n";
vi.mock("../../services/runtime",()=>({request:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it("reports actual shared access, blocked downloads and verification limitations",async()=>{
 vi.mocked(request).mockImplementation(async(_method,path)=>path==="/v1/security"?{api:{authentication:"bearer",browser_origins:"rejected",packaged_bind:"127.0.0.1"},workspace:{private:true,entries:[{name:"assets",exists:true,symlink:false,private:false}]},models:[{id:"whisper-tiny",state:"installed",error:null}]}:{model_downloads_allowed:false,active_model_operations:[],catalog_download_hosts:["example.com"]});
 render(<SafetyCenter t={translator("en")}/>);
 expect(await screen.findByText("Shared access")).toBeTruthy();
 expect(await screen.findByText("Model downloads blocked")).toBeTruthy();
 expect(screen.getByText(/Installed state does not certify/)).toBeTruthy();
});
