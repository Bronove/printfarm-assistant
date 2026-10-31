import { execFile, execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const root = path.resolve(import.meta.dirname, "..");
const exe = path.resolve(
  process.env.TUOZHU_E2E_EXE
    || path.join(root, "dist_v2", "PrintFarmAssistant", "PrintFarmAssistant.exe"),
);
let model = path.resolve(
  root,
  "..",
  "test_files",
  "pure_probe",
  "_color_meshes",
  "slot_06.stl",
);
let fixtureDir = null;
if (!fs.existsSync(model)) {
  fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), "printfarm-public-e2e-"));
  model = path.join(fixtureDir, "probe.stl");
  const vertices = [
    [0, 0, 0], [20, 0, 0], [0, 20, 0], [20, 20, 0],
    [0, 0, 10], [20, 0, 10], [0, 20, 10], [20, 20, 10],
  ];
  const triangles = [
    [0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6],
    [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
    [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5],
  ];
  const facets = triangles.map(([a, b, c]) => (
    "  facet normal 0 0 0\n"
    + "    outer loop\n"
    + `      vertex ${vertices[a].join(" ")}\n`
    + `      vertex ${vertices[b].join(" ")}\n`
    + `      vertex ${vertices[c].join(" ")}\n`
    + "    endloop\n"
    + "  endfacet\n"
  )).join("");
  fs.writeFileSync(
    model,
    `solid printfarm_probe\n${facets}endsolid printfarm_probe\n`,
    "ascii",
  );
}
const stepModel = path.resolve(
  process.env.TUOZHU_E2E_STEP
    || path.join(root, "..", "test_files", "block.stp"),
);
const edgeCandidates = [
  path.join(process.env["PROGRAMFILES(X86)"] ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.PROGRAMFILES ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.LOCALAPPDATA ?? "", "Microsoft/Edge/Application/msedge.exe"),
];
const executablePath = edgeCandidates.find((candidate) => fs.existsSync(candidate));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch("http://127.0.0.1:4180/api/health");
      const body = await response.json();
      if (response.ok && body.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("打包版本地服务启动超时");
}

async function stopProcessTree(pid) {
  if (!pid) return;
  await new Promise((resolve) => {
    execFile(
      "taskkill",
      ["/PID", String(pid), "/T", "/F"],
      { windowsHide: true },
      () => resolve(),
    );
  });
}

async function removeWithRetry(target) {
  let lastError;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    try {
      await rm(target, { recursive: true, force: true });
      return;
    } catch (error) {
      lastError = error;
      if (error?.code !== "EBUSY" && error?.code !== "EPERM") throw error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw lastError;
}

assert(fs.existsSync(exe), `找不到打包版程序：${exe}`);
assert(fs.existsSync(model), `找不到测试模型：${model}`);
assert(executablePath, "找不到 Microsoft Edge，无法运行桌面端真实路径测试");

try {
  const health = await fetch("http://127.0.0.1:4180/api/health").catch(() => null);
  if (health?.ok) {
    throw new Error("4180 端口已有拓竹助手在运行，请先关闭后再执行端到端测试");
  }
} catch (error) {
  if (error instanceof Error && error.message.includes("4180 端口")) throw error;
}

const outputDir = await mkdtemp(path.join(os.tmpdir(), "tuozhu-v2-e2e-"));
const dataDir = await mkdtemp(path.join(os.tmpdir(), "printfarm-data-e2e-"));
const configPath = path.join(dataDir, "config.json");
const originalConfig = await readFile(configPath, "utf8").catch((error) => {
  if (error?.code === "ENOENT") return null;
  throw error;
});
const config = originalConfig
  ? JSON.parse(originalConfig)
  : {
      machine: "Bambu Lab H2S 0.4 nozzle",
      process: "0.20mm Standard @BBL X1C",
      filament: "Bambu PLA Basic @BBL H2S",
      bed: "Textured PEI Plate",
    };
config.machine = "Bambu Lab H2S 0.4 nozzle";
config.process = "0.20mm Standard @BBL X1C";
config.filament = "Bambu PLA Basic @BBL H2S";
config.bed = "Textured PEI Plate";
config.output_dir = outputDir;
config.output_mode = "gcode";
await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");

let app;
let browser;
try {
  app = spawn(exe, [], {
    stdio: "ignore",
    windowsHide: true,
    env: { ...process.env, PRINTFARM_DATA_DIR: dataDir },
  });
  await waitForHealth();

  browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  await page.goto("http://127.0.0.1:4180/", { waitUntil: "domcontentloaded" });

  const modelInput = page.locator('input[type="file"][accept*=".stl"]');
  await modelInput.setInputFiles(model);
  await page.getByText("已导入 1 个模型，可以开始切片。").waitFor({ timeout: 30_000 });

  assert(
    await page.locator("details.advanced-settings").evaluate((element) => element.open),
    "更多切片参数没有默认展开",
  );
  assert(
    await page.getByLabel("输出类型").inputValue() === "gcode",
    "默认输出不是可直接打印 G-code 3MF",
  );

  await page.getByRole("button", { name: "开始切片" }).click();
  await page.getByText(/切片完成，输出目录：/).waitFor({ timeout: 120_000 });

  const outputs = (await readdir(outputDir)).filter((name) => name.endsWith(".gcode.3mf"));
  assert(outputs.length === 1, `预期生成 1 个 G-code 3MF，实际为 ${outputs.length} 个`);
  const output = path.join(outputDir, outputs[0]);
  assert(fs.statSync(output).size > 0, "生成的 G-code 3MF 为空");
  const archiveEntries = execFileSync("tar", ["-tf", output], { encoding: "utf8" });
  assert(
    archiveEntries.includes("Metadata/plate_1.gcode"),
    "生成的 3MF 内没有 plate_1.gcode",
  );

  console.log(`打包版用户路径通过：${output}`);
  if (fs.existsSync(stepModel)) {
    await page.getByRole("button", { name: "清空" }).click();
    await page.locator('input[type="file"][accept*=".stl"]').setInputFiles(stepModel);
    await page.getByText("已导入 1 个模型，可以开始切片。").waitFor({ timeout: 30_000 });
    await page.getByRole("button", { name: "开始切片" }).click();

    const stepDeadline = Date.now() + 180_000;
    let stepOutputs = [];
    while (Date.now() < stepDeadline) {
      const state = await fetch("http://127.0.0.1:4180/api/state")
        .then((response) => response.json())
        .catch(() => null);
      stepOutputs = (await readdir(outputDir))
        .filter((name) => name.endsWith(".gcode.3mf"));
      if (stepOutputs.length >= 2 && !state?.busy) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    assert(stepOutputs.length >= 2, "打包版没有完成 STEP 到 G-code 3MF 的真实切片");
    const stepOutput = stepOutputs.find((name) => name !== outputs[0]);
    assert(stepOutput, "没有找到 STEP 切片生成的新输出");
    const stepArchive = execFileSync(
      "tar",
      ["-tf", path.join(outputDir, stepOutput)],
      { encoding: "utf8" },
    );
    assert(
      stepArchive.includes("Metadata/plate_1.gcode"),
      "STEP 切片生成的 3MF 内没有 plate_1.gcode",
    );
    console.log(`打包版 STEP 用户路径通过：${path.join(outputDir, stepOutput)}`);
  }
} finally {
  await browser?.close().catch(() => {});
  await stopProcessTree(app?.pid);
  if (originalConfig === null) {
    await rm(configPath, { force: true });
  } else {
    await writeFile(configPath, originalConfig, "utf8");
  }
  await removeWithRetry(outputDir);
  await removeWithRetry(dataDir);
  if (fixtureDir) await removeWithRetry(fixtureDir);
}
