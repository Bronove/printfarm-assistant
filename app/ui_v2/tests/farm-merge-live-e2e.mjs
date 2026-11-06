import { execFile, execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const root = path.resolve(import.meta.dirname, "..");
const repoRoot = path.resolve(root, "..");
const edgeCandidates = [
  path.join(process.env["PROGRAMFILES(X86)"] ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.PROGRAMFILES ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.LOCALAPPDATA ?? "", "Microsoft/Edge/Application/msedge.exe"),
];
const executablePath = edgeCandidates.find((candidate) => fs.existsSync(candidate));
if (!executablePath) {
  throw new Error("找不到 Microsoft Edge，无法运行真实合盘 UI 测试。");
}

const sourceDir = path.join(repoRoot, "演示素材", "测试模型");
const sources = [
  path.join(sourceDir, "T模型_平放.stl"),
  path.join(sourceDir, "F模型_平放.stl"),
];
for (const source of sources) {
  if (!fs.existsSync(source)) {
    throw new Error(`缺少真实合盘测试模型：${source}`);
  }
}

const python = process.env.PRINTFARM_PYTHON
  || (fs.existsSync("D:\\python\\python.exe") ? "D:\\python\\python.exe" : "python");
const artifactRoot = process.env.FARM_E2E_ROOT
  ? path.resolve(process.env.FARM_E2E_ROOT)
  : os.tmpdir();
fs.mkdirSync(artifactRoot, { recursive: true });
const runRoot = fs.mkdtempSync(path.join(artifactRoot, "farm-ui-live-"));
const dataDir = path.join(runRoot, "data");
const outputDir = path.join(runRoot, "output");
fs.mkdirSync(dataDir, { recursive: true });
fs.mkdirSync(outputDir, { recursive: true });

const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

async function waitForHealth(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch("http://127.0.0.1:4180/api/health");
      const body = await response.json();
      if (response.ok && body.ok) return;
    } catch {
      // The local source server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("源码版本地服务启动超时");
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

const existingService = await fetch("http://127.0.0.1:4180/api/health")
  .then(() => true)
  .catch(() => false);
if (existingService) {
  throw new Error("4180 端口已有服务在运行，请先关闭后再执行源码真实合盘测试");
}

let serverProcess;
let browser;
try {
  serverProcess = spawn(python, ["-X", "utf8", "server.py"], {
    cwd: root,
    env: {
      ...process.env,
      PRINTFARM_DATA_DIR: dataDir,
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
    },
    stdio: "ignore",
    windowsHide: true,
  });
  await waitForHealth();

  browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.setDefaultTimeout(30_000);
  await page.route("**/api/choose-output", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ok: true, path: outputDir }),
  }));

  await page.goto("http://127.0.0.1:4180/", { waitUntil: "networkidle" });
  await page.route("**/api/import/file?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900));
    await route.continue();
  });
  await page.getByRole("button", { name: "批量切片" }).click();
  await page.getByRole("heading", { name: "多文件合盘排布" }).waitFor();
  await page.getByRole("button", { name: "紧凑", exact: true }).click();

  await page.locator('input[accept=".stl,.3mf,.step,.stp"]').first().setInputFiles(sources);
  await page.getByRole("status", { name: "正在处理" }).waitFor();
  const importScreenshot = path.join(runRoot, "farm-import-spinner.png");
  await page.screenshot({ path: importScreenshot, fullPage: true });
  await page.getByText("2 个文件已导入").waitFor({ timeout: 60_000 });

  await page.getByLabel("打印机", { exact: true }).selectOption({ label: "P1S" });
  await page.getByLabel("打印板", { exact: true }).selectOption("Textured PEI Plate");
  for (const source of sources) {
    const name = path.basename(source);
    await page.getByRole("spinbutton", { name: `${name} 打印数量` }).fill("2");
  }
  assert(
    await page.locator(".batch-merge-summary__stats strong").nth(1).textContent() === "4",
    "合计打印份数没有更新为 4",
  );

  await page.getByRole("button", { name: "更改" }).click();
  await page.getByText(outputDir).waitFor();
  await page.getByRole("button", { name: "生成可编辑 3MF" }).click();
  await page.getByText(/可编辑 3MF 生成完成.*盘面布局已生成，共 1 盘/).waitFor({
    timeout: 180_000,
  });

  const state = await page.evaluate(async () => {
    const response = await fetch("http://127.0.0.1:4180/api/state");
    return response.json();
  });
  assert(state?.task?.status === "done", `真实任务状态异常：${state?.task?.status}`);
  const result = state?.task?.results?.at(-1);
  assert(result?.layout_only === true, "批量合盘没有走可编辑 3MF 路径");
  assert(result?.layout_checked === false, "批量合盘不应执行切片预检");
  assert(result?.total_plates === 1, `应合成 1 盘，实际 ${result?.total_plates}`);
  assert(result?.needs_attention === false, "真实合盘出现待处理项");
  assert(result?.machine === "Bambu Lab P1S 0.4 nozzle", `机型未传到后端：${result?.machine}`);
  assert(
    typeof result?.editable_file === "string"
      && result.editable_file.endsWith(".3mf")
      && !result.editable_file.endsWith(".gcode.3mf"),
    "没有生成通用可编辑 3MF",
  );
  assert(
    Array.isArray(state?.task?.logs)
      && state.task.logs.some((line) => line.includes("LAYOUT EXIT")),
    "真实任务没有完成布局导出",
  );
  assert(
    result?.output_files?.length === 1 && fs.existsSync(result.output_files[0]),
    "可编辑合盘文件不存在",
  );
  const archive = execFileSync(
    "tar",
    ["-tf", result.output_files[0]],
    { encoding: "utf8" },
  );
  assert(
    archive.includes("3D/3dmodel.model")
      && !archive.split(/\r?\n/).some((name) => name.endsWith(".gcode")),
    "交付 3MF 不是可编辑工程，或仍包含 G-code",
  );
  const released = await page.evaluate(async () => {
    const response = await fetch("http://127.0.0.1:4180/api/import/release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    return response.json();
  });
  assert(released?.ok === true, "真实合盘测试结束后没有释放上传缓存");

  const screenshot = path.join(runRoot, "farm-merge-ui.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  const narrowScreenshot = path.join(runRoot, "farm-merge-ui-narrow.png");
  await page.setViewportSize({ width: 600, height: 960 });
  await page.screenshot({ path: narrowScreenshot, fullPage: true });
  console.log(JSON.stringify({
    ok: true,
    importScreenshot,
    screenshot,
    narrowScreenshot,
    output: result.output_files[0],
    plates: result.total_plates,
    machine: result.machine,
  }, null, 2));
} finally {
  await browser?.close().catch(() => {});
  await stopProcessTree(serverProcess?.pid);
  if (process.env.KEEP_FARM_E2E !== "1") {
    fs.rmSync(runRoot, { recursive: true, force: true });
  }
}
