import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";
import { preview } from "vite";

const root = path.resolve(import.meta.dirname, "..");
const edgeCandidates = [
  path.join(process.env["PROGRAMFILES(X86)"] ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.PROGRAMFILES ?? "", "Microsoft/Edge/Application/msedge.exe"),
  path.join(process.env.LOCALAPPDATA ?? "", "Microsoft/Edge/Application/msedge.exe"),
];
const executablePath = edgeCandidates.find((candidate) => fs.existsSync(candidate));

if (!executablePath) {
  throw new Error("找不到 Microsoft Edge，无法运行 UI 冒烟测试。");
}

const server = await preview({
  root,
  preview: {
    host: "127.0.0.1",
    port: 4177,
    strictPort: true,
  },
});

const browser = await chromium.launch({ executablePath, headless: true });

const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  let taskPolls = 0;
  let clientLogEvents = 0;
  await page.route("http://127.0.0.1:4180/api/log", (route) => {
    clientLogEvents += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.route("http://127.0.0.1:4180/api/config", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      machines: ["Bambu Lab H2S"],
      materials: ["PLA", "PETG", "ABS", "TPU"],
      machine: "Bambu Lab H2S",
      process: "0.20mm Standard @BBL X1C",
      filament: "Bambu PLA Basic @BBL P1S 0.4 nozzle",
      bed: "Textured PEI Plate",
      outputDir: "C:\\切片文件",
    }),
  }));
  await page.route("http://127.0.0.1:4180/api/logs", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ok: true, path: "C:\\logs", text: "本地日志测试" }),
  }));
  const metaPayload = {
    ok: true,
    version: "2.0.10",
    usage: {
      total: 12,
      events: [["slice_done", 3], ["app_start", 9]],
      recent: [],
    },
    learning: {
      summary: "1 条短语规则 / 2 条认可样本",
      phraseRules: [{
        norm: "薄层打印",
        overrides: { layer_height: "0.12" },
        enabled: true,
      }],
      defaults: { layer_height: "0.12" },
      samples: 2,
    },
  };
  await page.route("http://127.0.0.1:4180/api/meta", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(metaPayload),
  }));
  await page.route("http://127.0.0.1:4180/api/rules", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(metaPayload),
  }));
  await page.route("http://127.0.0.1:4180/api/import", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      jobs: [{
        path: "C:\\切片文件\\bridge-test.stl",
        name: "bridge-test.stl",
        size: 2048,
        preview: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8ioAAAAASUVORK5CYII=",
      }],
    }),
  }));
  await page.route("http://127.0.0.1:4180/api/slice", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      taskId: "task-test",
      busy: true,
      task: {
        id: "task-test",
        status: "running",
        progress: 0,
        message: "正在切片",
        logs: [],
        outputDir: "C:\\切片文件",
        startedAt: Date.now(),
        finishedAt: null,
      },
    }),
  }));
  await page.route("http://127.0.0.1:4180/api/state", (route) => {
    taskPolls += 1;
    const done = taskPolls > 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        busy: !done,
        task: {
          id: "task-test",
          status: done ? "done" : "running",
          progress: done ? 1 : 0.42,
          message: done ? "切片完成" : "正在切片 2/5",
          logs: [],
          outputDir: "C:\\切片文件",
          startedAt: Date.now() - 1000,
          finishedAt: done ? Date.now() : null,
        },
      }),
    });
  });
  await page.goto("http://127.0.0.1:4177/", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "切片工作台", exact: true }).waitFor();
  await page.getByRole("heading", { name: "排盘参数", exact: true }).waitFor();
  assert(
    await page.getByText("UI 预览", { exact: true }).count() === 0,
    "正式界面不应保留 UI 预览标记",
  );
  assert(
    await page.locator(".workflow-steps").count() === 0,
    "静态流程胶囊应从正式界面移除",
  );
  const brandIcon = page.getByTestId("app-brand-icon");
  assert(
    await brandIcon.evaluate((image) => image instanceof HTMLImageElement && image.naturalWidth > 0),
    "拓竹助手原图标没有正确加载",
  );
  assert(
    (await brandIcon.getAttribute("src"))?.includes("icon.ico"),
    "界面左上角没有使用原 icon.ico",
  );
  const commandLayout = await page.locator(".command-panel").evaluate((panel) => {
    const editor = panel.querySelector("textarea");
    if (!editor) return null;
    return {
      panelWidth: panel.getBoundingClientRect().width,
      editorWidth: editor.getBoundingClientRect().width,
    };
  });
  assert(
    commandLayout && commandLayout.editorWidth / commandLayout.panelWidth > 0.72,
    `一句话参数输入框占宽不足：${JSON.stringify(commandLayout)}`,
  );
  const exampleTrigger = page.getByRole("button", { name: "示例", exact: true });
  assert(
    await page.getByRole("button", { name: "H2S，支撑只放打印板，自动摆盘" }).count() === 0,
    "示例口令不应常驻占用输入区",
  );
  await exampleTrigger.hover();
  await page.getByRole("button", { name: "H2S，支撑只放打印板，自动摆盘" }).waitFor();
  const helpTrigger = page.getByRole("button", { name: "一句话修改参数说明" });
  await helpTrigger.hover();
  await page.getByRole("tooltip").waitFor();

  const settingsPanel = page.locator(".settings-panel");
  await settingsPanel.hover();
  await page.mouse.wheel(0, 420);
  await page.waitForTimeout(35);
  const scrollDuringAnimation = await settingsPanel.evaluate((element) => element.scrollTop);
  await page.waitForTimeout(220);
  const scrollAfterAnimation = await settingsPanel.evaluate((element) => element.scrollTop);
  assert(
    scrollDuringAnimation > 0 && scrollAfterAnimation >= scrollDuringAnimation,
    `设置区滚轮没有平滑跟随：${scrollDuringAnimation} -> ${scrollAfterAnimation}`,
  );
  await settingsPanel.evaluate((element) => { element.scrollTop = 0; });

  const settingsIcon = page.getByRole("button", { name: "设置" });
  await settingsIcon.hover();
  await page.mouse.down();
  await page.waitForTimeout(35);
  assert(
    await settingsIcon.evaluate((element) => getComputedStyle(element).transform !== "none"),
    "图标按下时没有缩放反馈",
  );
  await page.mouse.up();
  await page.getByRole("dialog", { name: "设置" }).waitFor();
  await page.getByRole("heading", { name: "打印习惯" }).waitFor();
  await page.getByRole("heading", { name: "使用数据" }).waitFor();
  await page.getByText("层高 = 0.12").waitFor();
  await page.getByText("薄层打印").waitFor();
  await page.getByText("本地日志测试").waitFor();
  assert(
    await page.getByText("账号", { exact: true }).count() === 0,
    "主程序不应再出现账号入口",
  );
  assert(
    await page.getByText("个人参数学习").count() === 0,
    "悬浮助手相关设置不应出现在软件端",
  );
  assert(
    await page.getByText("插件").count() === 0,
    "主程序本地日志窗口不应混入插件设置",
  );
  assert(clientLogEvents > 0, "界面操作没有写入本地日志");
  await page.keyboard.press("Escape");
  await page.getByRole("dialog", { name: "设置" }).waitFor({ state: "detached" });

  for (const viewport of [
    { width: 1440, height: 960 },
    { width: 1100, height: 820 },
    { width: 760, height: 1000 },
    { width: 440, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(
        () => requestAnimationFrame(resolve),
      )),
    );
    const layout = await page.evaluate(() => ({
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
    }));
    assert(
      layout.documentWidth <= layout.viewportWidth + 1
        && layout.bodyWidth <= layout.viewportWidth + 1,
      `${viewport.width}px 出现横向溢出：${JSON.stringify(layout)}`,
    );
  }

  await page.setViewportSize({ width: 1440, height: 960 });
  const actionButton = page.getByRole("button", {
    name: /^(生成排盘|开始切片)$/,
  });
  const buttonBox = await actionButton.boundingBox();
  assert(buttonBox && buttonBox.y + buttonBox.height <= 960, "桌面首屏看不到主操作按钮");

  const command = page.getByLabel("一句话参数和图片识别口令");
  assert(await command.inputValue() === "", "参数输入框初始应显示占位提示");
  assert(
    (await command.getAttribute("placeholder"))?.includes("说参数"),
    "参数输入框缺少初始说明",
  );
  assert(
    await page.getByLabel("支撑方式").inputValue() === "tree_plate",
    "支撑默认项没有保留树状支撑术语",
  );
  const printerSelect = page.getByLabel("打印机");
  assert(
    await printerSelect.evaluate(
      (element) => getComputedStyle(element).appearance === "none",
    ),
    "机型下拉框仍显示原生箭头",
  );
  assert(
    await printerSelect.locator("xpath=ancestor::label[1]").locator(":scope > svg").count() === 1,
    "机型选择应只保留一个箭头",
  );
  assert(
    (await page.getByLabel("支撑方式").locator("option").allTextContents())
      .includes("树状支撑（仅打印板生成）"),
    "支撑选项缺少原版全称",
  );
  await command.fill("填充改直线");
  assert(
    await page.getByLabel("填充图案").inputValue() === "lines",
    "一句话没有同步直线填充",
  );
  assert(
    await page.getByRole("switch", { name: "交给 Bambu 自动排列" })
      .getAttribute("aria-checked") === "false",
    "自动排列默认应为关闭",
  );
  assert(
    await page.getByRole("switch", { name: "自动定向" })
      .getAttribute("aria-checked") === "false",
    "自动定向默认应为关闭",
  );
  await command.fill("H2S，层高 0.2，填充 35%，不要支撑，关闭自动排列");
  await page.getByText("已同步：层高 0.20 mm · 填充 35% · 不生成支撑").waitFor();
  assert(
    await page.getByRole("spinbutton", { name: "层高 mm" }).inputValue() === "0.20",
    "一句话层高没有即时同步",
  );
  assert(
    await page.getByRole("spinbutton", { name: "填充 %" }).inputValue() === "35",
    "一句话填充没有即时同步",
  );
  assert(
    await page.getByLabel("支撑方式").inputValue() === "off",
    "一句话支撑设置没有即时同步",
  );
  await page.getByText("简单文件流程").waitFor();
  assert(
    await page.getByRole("switch", { name: "交给 Bambu 自动排列" })
      .getAttribute("aria-checked") === "false",
    "一句话关闭自动排列没有同步到切片工作台",
  );

  await page.getByLabel("妙妙工具箱，0 项已启用").click();
  await page.getByRole("switch", { name: "隐藏 Z 缝" }).waitFor();
  await page.getByRole("switch", { name: "顶面熨烫" }).waitFor();
  const hideSeamHelp = page
    .locator(".switch-row")
    .filter({ hasText: "隐藏 Z 缝" })
    .locator(".help-tip summary")
    .first();
  await hideSeamHelp.hover();
  await page.getByRole("paragraph").filter({ hasText: "适合手办、摆件" }).waitFor();
  const helpGeometry = await page.evaluate(() => {
    const summary = document.querySelector(
      ".switch-row .help-tip summary",
    )?.getBoundingClientRect();
    const tooltip = document.querySelector(
      ".switch-row .help-tip > p",
    )?.getBoundingClientRect();
    const panel = document.querySelector(
      ".settings-panel",
    )?.getBoundingClientRect();
    return summary && tooltip && panel
      ? {
          summaryWidth: summary.width,
          summaryHeight: summary.height,
          tooltipLeft: tooltip.left,
          tooltipRight: tooltip.right,
          panelLeft: panel.left,
          panelRight: panel.right,
        }
      : null;
  });
  assert(
    helpGeometry
      && Math.abs(helpGeometry.summaryWidth - helpGeometry.summaryHeight) < 2,
    `帮助按钮被拉成了椭圆：${JSON.stringify(helpGeometry)}`,
  );
  assert(
    helpGeometry
      && helpGeometry.tooltipLeft >= helpGeometry.panelLeft
      && helpGeometry.tooltipRight <= helpGeometry.panelRight,
    `帮助说明被设置栏裁切：${JSON.stringify(helpGeometry)}`,
  );
  await page.mouse.move(40, 40);
  await page.waitForTimeout(220);
  assert(
    await page.locator(".switch-row").filter({ hasText: "隐藏 Z 缝" })
      .locator(".help-tip").evaluate((element) => !element.open),
    "帮助说明移开鼠标后没有自动收起",
  );
  await command.fill("隐藏 Z 缝，顶面熨烫");
  assert(
    await page.getByRole("switch", { name: "隐藏 Z 缝" }).getAttribute("aria-checked") === "true"
      && await page.getByRole("switch", { name: "顶面熨烫" }).getAttribute("aria-checked") === "true",
    "一句话参数没有同步到妙妙工具箱",
  );
  assert(
    await page.getByText("2 项启用").isVisible(),
    "妙妙工具箱没有显示启用数量",
  );

  await page.getByRole("button", { name: "切片工作台" }).click();
  await command.fill("PETG，高温板，克隆4个，最省空间，最少支撑");
  assert(
    await page.locator("details.advanced-settings").evaluate((element) => element.open),
    "更多切片参数没有默认展开",
  );
  assert(await page.getByLabel("耗材").inputValue() === "PETG", "一句话没有同步耗材");
  assert(
    await page.getByLabel("打印板").inputValue() === "High Temp Plate",
    "一句话没有同步打印板",
  );
  assert(
    await page.getByRole("spinbutton", { name: "克隆数量 个" }).inputValue() === "4",
    "一句话没有同步克隆数量",
  );
  assert(
    await page.getByRole("switch", { name: "最省空间" }).getAttribute("aria-checked") === "true"
      && await page.getByRole("switch", { name: "最少支撑" }).getAttribute("aria-checked") === "true",
    "一句话没有同步高级开关",
  );
  await page.getByLabel("输出类型").selectOption("3mf");
  assert(
    await page.getByRole("switch", { name: "最省空间" }).isDisabled()
      && await page.getByRole("switch", { name: "最少支撑" }).isDisabled()
      && await page.getByRole("switch", { name: "最省空间" }).getAttribute("aria-checked") === "false"
      && await page.getByRole("switch", { name: "最少支撑" }).getAttribute("aria-checked") === "false",
    "仅生成 3MF 时不应允许无效的切片优化开关",
  );
  await page.getByLabel("输出类型").selectOption("gcode");

  await page.route("http://127.0.0.1:4180/api/ocr", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      text: "层高 0.24，填充 45%，不要支撑",
      note: "",
    }),
  }));
  await page.locator('input[accept="image/*"]').setInputFiles({
    name: "params.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8ioAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await page.getByText("已识别 params.png").waitFor();
  assert(
    await page.getByRole("spinbutton", { name: "层高 mm" }).inputValue() === "0.24",
    "图片识别文字没有即时同步层高",
  );
  assert(
    await page.getByLabel("支撑方式").inputValue() === "off",
    "图片识别文字没有即时同步支撑",
  );

  await page.getByText("导入模型后在这里检查分组").waitFor();
  assert(await actionButton.isDisabled(), "清空模型后主操作仍可点击");
  await page.getByText("先导入简单文件，工作台会保留当前朝向直接切片").waitFor();
  await page.getByRole("button", { name: "载入演示模型" }).click();
  assert(await actionButton.isDisabled(), "演示模型不应允许启动真实切片");
  await page.getByText("当前是演示任务").waitFor();

  await page.getByRole("button", { name: "清空" }).click();
  await page.getByRole("button", { name: "切片工作台" }).click();
  await page.locator('input[accept=".stl,.3mf,.step,.stp"]').setInputFiles({
    name: "bridge-test.stl",
    mimeType: "model/stl",
    buffer: Buffer.from("solid test\nendsolid test\n"),
  });
  await page.getByText("已导入 1 个模型，可以开始切片").waitFor();
  assert(
    await page.locator(".queue-item__preview img").count() === 1,
    "任务卡没有显示模型缩略图",
  );
  const workbenchButton = page.getByRole("button", { name: "开始切片" });
  assert(!(await workbenchButton.isDisabled()), "真实模型导入后主操作仍不可用");
  await workbenchButton.click();
  await page.getByRole("button", { name: "停止切片" }).waitFor();
  await page.getByText("切片完成，输出目录").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "打开所在位置" }).waitFor();
  assert(taskPolls >= 2, "切片任务没有进入状态轮询");

  assert(
    await page.getByRole("button", { name: "多色排盘" }).count() === 0,
    "公开版不应显示多色排盘入口",
  );
  assert(
    await page.getByRole("button", { name: "手办模式" }).count() === 0,
    "公开版不应显示手办模式入口",
  );
  assert(
    await page.getByRole("button", { name: "打开悬浮窗助手" }).count() === 0,
    "公开版不应显示悬浮助手入口",
  );

  const widget = await browser.newPage({ viewport: { width: 380, height: 620 } });
  await widget.goto("http://127.0.0.1:4177/?widget=assistant", {
    waitUntil: "networkidle",
  });
  await widget.evaluate(() => document.fonts.ready);
  await widget.getByRole("button", { name: "切片工作台" }).waitFor();
  assert(
    await widget.getByText("拓竹悬浮助手").count() === 0,
    "公开版不能通过页面参数打开悬浮助手",
  );
  await widget.close();

  console.log("UI 冒烟测试通过：公开模式、真实任务桥接、参数和 OCR");
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}
