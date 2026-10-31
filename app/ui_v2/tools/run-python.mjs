import { spawnSync } from "node:child_process";

const python = process.env.PRINTFARM_PYTHON || "python";
const result = spawnSync(python, process.argv.slice(2), {
  stdio: "inherit",
  windowsHide: true,
  env: {
    ...process.env,
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
  },
});

if (result.error) {
  console.error(
    `无法启动 Python（${python}）。请设置 PRINTFARM_PYTHON 指向 Python 3.12。`,
  );
  process.exit(1);
}
process.exit(result.status ?? 1);
