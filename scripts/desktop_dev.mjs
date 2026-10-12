/** Validate the source interpreter before opening a disconnected desktop. */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const python =
  process.env.NEXUS_RUNTIME_PYTHON ||
  resolve(
    root,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
function fail(message) {
  console.error(`NEXUS: ${message}`);
  process.exit(1);
}
if (!existsSync(python))
  fail(
    `Python environment not found: ${python}\nCreate .venv and install: python -m pip install -e "./runtime[ai,test]" (see README).`,
  );
const check = spawnSync(
  python,
  ["-c", "import nexus_runtime, fastapi, uvicorn"],
  { cwd: root, encoding: "utf8", timeout: 30000 },
);
if (check.error || check.status !== 0)
  fail(
    `Runtime dependencies unavailable in ${python}\n${check.error?.message || check.stderr}`,
  );
const cli = resolve(root, "apps/desktop/node_modules/@tauri-apps/cli/tauri.js");
if (!existsSync(cli))
  fail("Install frontend dependencies first: cd apps/desktop && npm ci");
const result = spawnSync(
  process.execPath,
  [
    cli,
    "dev",
    "--config",
    "src-tauri/tauri.dev.conf.json",
    ...process.argv.slice(2),
  ],
  {
    cwd: resolve(root, "apps/desktop"),
    stdio: "inherit",
    env: { ...process.env, NEXUS_RUNTIME_PYTHON: python },
  },
);
if (result.error) fail(result.error.message);
process.exit(result.status ?? 1);
