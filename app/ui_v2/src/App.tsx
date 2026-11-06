import { useEffect, useMemo, useRef, useState } from "react";
import AppHeader from "./components/AppHeader";
import BatchMergeWorkspace from "./components/BatchMergeWorkspace";
import ImportCard from "./components/ImportCard";
import ImportPolicyDialog from "./components/ImportPolicyDialog";
import QueueCard from "./components/QueueCard";
import SettingsPanel from "./components/SettingsPanel";
import SettingsDialog from "./components/SettingsDialog";
import SmartCommandBar from "./components/SmartCommandBar";
import StatusBanner from "./components/ui/StatusBanner";
import { DEMO_JOBS, MODES } from "./data";
import { parseParameterCommand } from "./parameters";
import {
  cancelTask,
  chooseOutput,
  getBridgeConfig,
  getTaskState,
  openOutput,
  parseOnServer,
  releaseUploads,
  startSliceJob,
  uploadModels,
  type BridgeImportedFile,
} from "./bridge";
import type {
  FileParameterSummary,
  ImportParameterPolicy,
  ModelJob,
  OverridableParameter,
  SliceSettings,
  WorkspaceMode,
} from "./types";
import { logLocal } from "./client-log";

const INITIAL_SETTINGS: SliceSettings = {
  printer: "Bambu Lab H2S",
  material: "PLA",
  bedType: "Textured PEI Plate",
  layerHeight: "0.16",
  infill: "15",
  pattern: "grid",
  supportMode: "tree_plate",
  autoArrange: false,
  orientation: false,
  tightPacking: false,
  minSupport: false,
  clone: "1",
  outputMode: "gcode",
  maxColors: "4",
  multicolorStrategy: "zero_flush",
  targetHours: "4",
  hideSeam: false,
  topIroning: false,
  batchOutputMode: "combined",
  supportOverlap: false,
};

function formatBytes(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function jobsFromFiles(files: File[]): ModelJob[] {
  return files
    .filter((file) => /\.(stl|3mf|step|stp)$/i.test(file.name))
    .map((file) => {
      const relativePath = file.webkitRelativePath || file.name;
      return {
        id: `local:${relativePath}-${file.lastModified}-${file.size}`,
        name: relativePath,
        sizeLabel: formatBytes(file.size),
        material: "待识别",
        color: "",
        state: "ready",
        quantity: "1",
        parameterSource: "current",
      };
    });
}

interface PendingImportReview {
  loading: boolean;
  imported: BridgeImportedFile[];
  localNames: string[];
  issues: string[];
  error?: string;
}

const POLICY_FIELDS: Partial<Record<keyof SliceSettings, OverridableParameter>> = {
  layerHeight: "layerHeight",
  infill: "infill",
  pattern: "pattern",
  supportMode: "support",
};

function applyFileValues(
  current: SliceSettings,
  policy: ImportParameterPolicy,
  file: FileParameterSummary,
): SliceSettings {
  const pattern = file.pattern?.toLowerCase();
  const patternValue: SliceSettings["pattern"] = pattern === "line"
    ? "lines"
    : pattern && ["grid", "lines", "gyroid", "honeycomb", "cubic"].includes(pattern)
      ? pattern as SliceSettings["pattern"]
      : current.pattern;
  const supportValue = !file.supportEnabled
    ? "off"
    : file.supportType?.toLowerCase().startsWith("tree")
      ? file.supportPlateOnly ? "tree_plate" : "tree_all"
      : file.supportPlateOnly ? "normal_plate" : "normal_all";
  return {
    ...current,
    layerHeight: !policy.overrides.layerHeight && file.layerHeight
      ? String(file.layerHeight).replace(/mm$/i, "").trim()
      : current.layerHeight,
    infill: !policy.overrides.infill && file.infill
      ? String(file.infill).replace(/%$/, "").trim()
      : current.infill,
    pattern: !policy.overrides.pattern && file.pattern
      ? patternValue
      : current.pattern,
    supportMode: !policy.overrides.support
      && typeof file.supportEnabled === "boolean"
      ? supportValue
      : current.supportMode,
    parameterPolicy: policy,
  };
}

function markExplicitOverride(
  current: SliceSettings,
  key: keyof SliceSettings,
): SliceSettings {
  const overrideKey = POLICY_FIELDS[key];
  const policy = current.parameterPolicy;
  if (!overrideKey || !policy || policy.mode === "habit") return current;
  return {
    ...current,
    parameterPolicy: {
      mode: "custom",
      overrides: {
        ...policy.overrides,
        [overrideKey]: true,
      },
    },
  };
}

export default function App() {
  const [activeMode, setActiveMode] = useState<WorkspaceMode>("workbench");
  const [jobs, setJobs] = useState<ModelJob[]>([]);
  const [settings, setSettings] = useState<SliceSettings>(INITIAL_SETTINGS);
  const [command, setCommand] = useState("");
  const [summaries, setSummaries] = useState<string[]>([]);
  const [recentKeys, setRecentKeys] = useState<Array<keyof SliceSettings>>([]);
  const highlightTimer = useRef<number | null>(null);
  const parseTimer = useRef<number | null>(null);
  const parseGeneration = useRef(0);
  const [banner, setBanner] = useState<string | null>(
    "界面已就绪。导入模型后即可读取参数并开始切片。",
  );
  const [generating, setGenerating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingImport, setPendingImport] = useState<PendingImportReview | null>(null);
  const [taskLogs, setTaskLogs] = useState<string[]>([]);
  const [completedOutputDir, setCompletedOutputDir] = useState<string | null>(null);
  const [outputDir, setOutputDir] = useState("C:\\切片文件");
  const [machines, setMachines] = useState(["Bambu Lab H2S"]);
  const [materials, setMaterials] = useState(["PLA", "PETG", "ABS", "TPU"]);

  const activeDefinition = useMemo(
    () => MODES.find((mode) => mode.id === activeMode) ?? MODES[0],
    [activeMode],
  );
  const sliceableJobs = jobs.filter((job) => job.serverPath);
  const canGenerate = sliceableJobs.length > 0;
  const mergedBatch = activeMode === "batch"
    && settings.batchOutputMode === "combined";
  const actionHint = sliceableJobs.length
    ? activeMode === "workbench"
      ? `将对 ${sliceableJobs.length} 个简单文件按当前参数直接切片。`
      : activeMode === "multicolor"
        ? `将按多色策略处理 ${sliceableJobs.length} 个 3MF，并执行 Bambu 支撑检修。`
      : activeMode === "batch" && mergedBatch
        ? `将按数量展开 ${sliceableJobs.length} 个文件，合并为一个可在 Bambu 中继续编辑的多盘 3MF。`
      : activeMode === "figurine"
        ? `将保留 ${sliceableJobs.length} 个手办文件的稳定朝向并检查细支撑。`
      : `将按同一套参数连续处理 ${sliceableJobs.length} 个文件。`
    : jobs.length
      ? "当前是演示任务。导入真实模型后才能启动切片。"
    : activeMode === "workbench"
      ? "先导入简单文件，工作台会保留当前朝向直接切片。"
      : "先选择模型文件夹，再按同一套参数连续切片。";
  const bannerTone = !banner
    ? "info"
    : /失败|无法|未连接|不存在|错误|不支持/.test(banner)
      ? "error"
      : /已取消|注意|未通过|需要处理/.test(banner)
        ? "warning"
        : /完成|已导入|已就绪/.test(banner)
          ? "success"
          : "info";
  const bannerTitle = bannerTone === "error"
    ? "需要处理"
    : bannerTone === "warning"
      ? "请留意"
      : bannerTone === "success"
        ? "界面已就绪"
        : "当前状态";

  const applyCommand = (value: string) => {
    setCommand(value);
    const parsed = parseParameterCommand(value);
    setSettings((current) => {
      let next = { ...current, ...parsed.patch };
      for (const field of parsed.fields) {
        next = markExplicitOverride(next, field);
      }
      return next;
    });
    setSummaries(parsed.summaries);
    setRecentKeys(parsed.fields);
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setRecentKeys([]), 1200);
    if (parseTimer.current !== null) window.clearTimeout(parseTimer.current);
    const generation = ++parseGeneration.current;
    parseTimer.current = window.setTimeout(() => {
      void parseOnServer(
        value,
        sliceableJobs.map((job) => job.serverPath as string),
      )
        .then((result) => {
          if (generation === parseGeneration.current) setSummaries(result.parts);
        })
        .catch(() => {
          if (generation === parseGeneration.current) {
            setSummaries(parsed.summaries);
          }
        });
    }, 140);
  };

  useEffect(() => () => {
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    if (parseTimer.current !== null) window.clearTimeout(parseTimer.current);
  }, []);

  useEffect(() => {
    void getBridgeConfig()
      .then((config) => {
        setOutputDir(config.outputDir || "C:\\切片文件");
        if (config.machines?.length) setMachines(config.machines);
        if (config.materials?.length) setMaterials(config.materials);
        setSettings((current) => ({
          ...current,
          printer: config.machine
            ? config.machine.replace(/\s+0\.\d+\s+nozzle$/i, "")
            : current.printer,
          bedType: config.bed || current.bedType,
        }));
      })
      .catch(() => {
        setBanner("本机切片服务未连接。界面可预览，导入和切片需要先启动 server.py。");
      });
  }, []);

  useEffect(() => {
    if (!generating) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      void getTaskState()
        .then((state) => {
          if (disposed || !state.task) return;
          const task = state.task;
          const result = task.results?.[task.results.length - 1];
          const needsAttention = Boolean(result?.needs_attention);
          setTaskLogs(task.logs);
          setJobs((current) => current.map((job) => {
            if (!job.serverPath) return job;
            if (task.status === "done") {
              return {
                ...job,
                state: needsAttention ? "error" : "done",
                progress: 100,
                error: needsAttention
                  ? result?.warnings?.join("；") || "部分结果需要处理"
                  : undefined,
                outputDir: task.outputDir || outputDir,
              };
            }
            if (task.status === "error") {
              return { ...job, state: "error", error: task.message };
            }
            if (task.status === "cancelled") {
              return {
                ...job,
                state: "ready",
                progress: 0,
                error: undefined,
                outputDir: undefined,
              };
            }
            return {
              ...job,
              state: "printing",
              progress: Math.round(task.progress * 100),
              error: undefined,
            };
          }));
          if (task.status === "running") {
            setBanner(`${Math.round(task.progress * 100)}% · ${task.message}`);
            return;
          }
          setGenerating(false);
          if (task.status === "done") {
            setCompletedOutputDir(task.outputDir || outputDir);
            const layoutOnly = Boolean(
              result?.layout_only
              || (result?.editable_file && !result?.print_file),
            );
            const plateTimes = (result?.plates || [])
              .map((plate, index) => (
                plate.actual_hours != null || plate.printTimeS != null
                  ? `盘${index + 1} ${
                      plate.actual_hours != null
                        ? plate.actual_hours.toFixed(2)
                        : (Number(plate.printTimeS) / 3600).toFixed(2)
                    }h`
                  : ""
              ))
              .filter(Boolean);
            const checkText = result?.needs_attention
              ? "；部分文件未通过，详见问题清单"
              : layoutOnly
                ? `${result?.layout_checked
                  ? "；Bambu 布局预检通过"
                  : "；盘面布局已生成"}${
                  result?.total_plates ? `，共 ${result.total_plates} 盘` : ""
                }`
              : result?.slice_checked
              ? `；Bambu 检修通过${
                  result?.total_plates ? `，共 ${result.total_plates} 盘` : ""
                }${plateTimes.length ? `，${plateTimes.join(" / ")}` : ""}`
              : "";
            setBanner(
              `${layoutOnly
                ? "可编辑 3MF 生成完成"
                : `${activeMode === "multicolor" ? "多色排盘" : "切片"}完成`}${checkText}，输出目录：${task.outputDir || outputDir}`,
            );
          } else if (task.status === "cancelled") {
            setCompletedOutputDir(null);
            setBanner("切片已取消。");
          } else {
            setBanner(`切片失败：${task.message}`);
          }
        })
        .catch((error) => {
          if (disposed) return;
          setBanner(
            "暂时无法读取切片状态，正在自动重试；后台任务可能仍在运行。"
            + ` ${error instanceof Error ? error.message : error}`,
          );
        });
    }, 650);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeMode, generating, outputDir]);

  useEffect(() => {
    const loadDemo = () => {
      setJobs(DEMO_JOBS);
      setBanner("已重新载入演示模型。");
    };
    window.addEventListener("load-demo-jobs", loadDemo);
    return () => window.removeEventListener("load-demo-jobs", loadDemo);
  }, []);

  const completeImport = (
    importedFiles: BridgeImportedFile[],
    issues: string[] = [],
    policy?: ImportParameterPolicy,
  ) => {
    const uploaded = importedFiles.map((item) => ({
      id: `server:${item.path}`,
      name: item.relativePath || item.name,
      sizeLabel: formatBytes(item.size),
      material: item.material || "待识别",
      color: item.color || "",
      state: "ready" as const,
      serverPath: item.path,
      previewUrl: item.preview,
      quantity: "1",
      parameterSource: (
        item.fileSettings?.hasEmbeddedSettings ? "file" : "current"
      ) as "file" | "current",
      mergeParts: item.mergeParts,
      mergeIssue: item.mergeIssue,
    }));
    if (mergedBatch) resetBatchOutcome();
    setJobs((current) => [...current, ...uploaded]);
    const sourceFile = importedFiles.find(
      (item) => item.fileSettings?.hasEmbeddedSettings,
    )?.fileSettings;
    if (policy && sourceFile && policy.mode !== "habit") {
      setSettings((current) => applyFileValues(current, policy, sourceFile));
    } else {
      setSettings((current) => ({
        ...current,
        parameterPolicy: policy,
      }));
    }
    const parameterLabel = policy
      ? policy.mode === "file"
        ? "参数跟随文件"
        : policy.mode === "habit"
          ? "参数使用当前习惯"
          : `参数逐项覆盖 ${Object.values(policy.overrides).filter(Boolean).length} 项`
      : "";
    setBanner(
      `已导入 ${uploaded.length} 个模型，可以开始切片。`
      + (parameterLabel ? ` ${parameterLabel}。` : "")
      + (issues.length ? ` 注意：${issues.join("；")}` : ""),
    );
  };

  const addFiles = (files: File[]) => {
    logLocal("导入", "用户选择模型", {
      files: files.map((file) => ({ name: file.name, size: file.size })),
    });
    const next = jobsFromFiles(files);
    if (!next.length) {
      setBanner("没有识别到支持的模型文件。请选择 STL、3MF、STEP 或 STP。");
      return;
    }
    const known = new Set(jobs.map((job) => job.id));
    let unique = next.filter((job) => !known.has(job.id));
    let limitNote = "";
    if (mergedBatch) {
      const remaining = Math.max(0, 10 - jobs.length);
      if (unique.length > remaining) {
        limitNote = `；单次最多 10 个不同文件，已忽略 ${unique.length - remaining} 个`;
        unique = unique.slice(0, remaining);
      }
    }
    setBanner(
      unique.length
        ? `正在导入 ${unique.length} 个模型文件…${limitNote}`
        : limitNote || "这些模型已经在任务队列里。",
    );
    if (!unique.length) return;

    const uniqueIds = new Set(unique.map((job) => job.id));
    const filesToUpload = files.filter((file) => {
      const relativePath = file.webkitRelativePath || file.name;
      return uniqueIds.has(
        `local:${relativePath}-${file.lastModified}-${file.size}`,
      );
    });
    const needsParameterChoice = (
      !mergedBatch
      && filesToUpload.some((file) => /\.3mf$/i.test(file.name))
    );
    if (needsParameterChoice) {
      setPendingImport({
        loading: true,
        imported: [],
        localNames: unique.map((job) => job.name),
        issues: [],
      });
    }

    setImporting(true);
    void uploadModels(filesToUpload, (progress) => {
      const percent = Math.round(
        progress.loadedBytes / Math.max(1, progress.totalBytes) * 100,
      );
      setBanner(
        `正在导入 ${progress.fileIndex}/${progress.fileCount}：`
        + `${progress.fileName}（${percent}%）`,
      );
    })
      .then((result) => {
        const hasEmbeddedSettings = result.jobs.some(
          (job) => job.fileSettings?.hasEmbeddedSettings,
        );
        if (needsParameterChoice && hasEmbeddedSettings) {
          setPendingImport({
            loading: false,
            imported: result.jobs,
            localNames: unique.map((job) => job.name),
            issues: result.issues ?? [],
          });
          return;
        }
        setPendingImport(null);
        completeImport(result.jobs, result.issues);
      })
      .catch((error) => {
        if (needsParameterChoice) {
          setPendingImport((current) => current ? {
            ...current,
            loading: false,
            error: error instanceof Error ? error.message : String(error),
          } : null);
        }
        setBanner(`模型导入失败：${error instanceof Error ? error.message : error}`);
      })
      .finally(() => setImporting(false));
  };

  const generate = async () => {
    logLocal("切片", "用户点击开始切片", {
      mode: activeMode,
      models: sliceableJobs.map((job) => job.serverPath),
    });
    if (!sliceableJobs.length) {
      setBanner("当前只有演示模型。请先导入真实文件，再启动切片。");
      return;
    }
    if (mergedBatch) {
      if (sliceableJobs.length > 10) {
        setBanner("合并排盘单次最多支持 10 个不同文件。");
        return;
      }
      const invalid = sliceableJobs.find((job) => {
        const quantity = Number(job.quantity || 1);
        return !Number.isInteger(quantity) || quantity < 1 || quantity > 999;
      });
      if (invalid) {
        setBanner(`${invalid.name} 的打印数量必须在 1–999 之间。`);
        return;
      }
      const mergeIssue = sliceableJobs.find((job) => job.mergeIssue);
      if (mergeIssue) {
        setBanner(
          `${mergeIssue.name}：${mergeIssue.mergeIssue || "当前文件不符合合并排盘条件"}`,
        );
        return;
      }
    }
    setGenerating(true);
    setTaskLogs([]);
    setCompletedOutputDir(null);
    setBanner("正在准备切片任务…");
    try {
      await startSliceJob({
        mode: activeMode,
        models: sliceableJobs.map((job) => job.serverPath as string),
        settings,
        command,
        outputDir,
        batchItems: mergedBatch
          ? sliceableJobs.map((job) => ({
              path: job.serverPath as string,
              quantity: Math.max(1, Number(job.quantity || 1)),
              parameterSource: job.parameterSource || "file",
            }))
          : undefined,
      });
    } catch (error) {
      setGenerating(false);
      setBanner(`无法启动切片：${error instanceof Error ? error.message : error}`);
    }
  };

  const stop = async () => {
    logLocal("任务", "用户点击停止切片");
    try {
      await cancelTask();
      setBanner("正在停止切片…");
    } catch (error) {
      setBanner(`停止失败：${error instanceof Error ? error.message : error}`);
    }
  };

  const updateSetting = <K extends keyof SliceSettings,>(
    key: K,
    value: SliceSettings[K],
  ) => {
    setSettings((current) => {
      let next: SliceSettings = { ...current, [key]: value };
      if (key === "outputMode" && value === "3mf") {
        next.tightPacking = false;
        next.minSupport = false;
      }
      next = markExplicitOverride(next, key);
      return next;
    });
    setRecentKeys([key]);
  };

  const resetBatchOutcome = () => {
    setJobs((current) => current.map((job) => (
      job.state === "done" || job.state === "error"
        ? { ...job, state: "ready", progress: 0, error: undefined }
        : job
    )));
    setCompletedOutputDir(null);
  };

  const updateBatchSetting = <K extends keyof SliceSettings,>(
    key: K,
    value: SliceSettings[K],
  ) => {
    updateSetting(key, value);
    resetBatchOutcome();
  };

  const removeJob = (jobId: string) => {
    const removed = jobs.find((job) => job.id === jobId);
    const remaining = jobs.filter((job) => job.id !== jobId);
    setJobs(remaining);
    setCompletedOutputDir(null);
    if (mergedBatch) resetBatchOutcome();
    if (!remaining.length && !generating) {
      void releaseUploads().catch(() => undefined);
    }
    if (removed) {
      setBanner(`已将 ${removed.name} 从任务队列移除，源文件没有删除。`);
    }
  };

  const clearJobs = () => {
    setJobs([]);
    setTaskLogs([]);
    setCompletedOutputDir(null);
    setBanner("已清空任务队列，源文件没有删除。");
    if (!generating) void releaseUploads().catch(() => undefined);
  };

  const openFolder = (path: string) => {
    void openOutput(path).catch((error) => {
      setBanner(
        `无法打开输出位置：${error instanceof Error ? error.message : error}`,
      );
    });
  };

  return (
    <div className="app-shell">
      <AppHeader
        modes={MODES}
        activeMode={activeMode}
        onModeChange={(mode) => {
          logLocal("界面", "切换工作模式", { mode });
          setActiveMode(mode);
          if (mode === "figurine") {
            setSettings((current) => ({
              ...current,
              hideSeam: true,
              tightPacking: false,
              minSupport: false,
            }));
          }
        }}
        onSettingsOpen={() => {
          logLocal("设置", "打开软件设置");
          setSettingsOpen(true);
        }}
      />

      <main className={`app-main${mergedBatch ? " app-main--batch-merge" : ""}`}>
        {mergedBatch ? (
          <BatchMergeWorkspace
            jobs={jobs}
            settings={settings}
            machines={machines}
            materials={materials}
            outputDir={outputDir}
            busy={generating}
            importing={importing}
            statusMessage={banner || ""}
            onFiles={addFiles}
            onSettingChange={updateBatchSetting}
            onQuantityChange={(jobId, quantity) => {
              setJobs((current) => current.map((job) => (
                job.id === jobId
                  ? { ...job, quantity, state: "ready", progress: 0 }
                  : job
              )));
              resetBatchOutcome();
            }}
            onReorder={(fromId, toId) => {
              setJobs((current) => {
                const from = current.findIndex((job) => job.id === fromId);
                const to = current.findIndex((job) => job.id === toId);
                if (from < 0 || to < 0 || from === to) return current;
                const next = [...current];
                const [moving] = next.splice(from, 1);
                next.splice(to, 0, moving);
                return next;
              });
              resetBatchOutcome();
            }}
            onRemove={removeJob}
            onClear={clearJobs}
            onGenerate={generate}
            onCancel={stop}
            onOpenOutput={() => openFolder(completedOutputDir || outputDir)}
            onChooseOutput={() => {
              void chooseOutput()
                .then((result) => setOutputDir(result.path))
                .catch((error) => {
                  setBanner(
                    `选择输出目录失败：${error instanceof Error ? error.message : error}`,
                  );
                });
            }}
          />
        ) : (
          <>
        <section className="workspace-intro">
          <div>
            <h1>{activeDefinition.label}</h1>
            <p>{activeDefinition.description}</p>
          </div>
        </section>

        {banner ? (
          <StatusBanner
            tone={bannerTone}
            title={bannerTitle}
            loading={importing}
            action={
              <button className="text-button" type="button" onClick={() => setBanner(null)}>
                知道了
              </button>
            }
          >
              {banner}
          </StatusBanner>
        ) : null}

        <div className="workspace-grid">
          <div className="workspace-main">
            <SmartCommandBar
              value={command}
              summaries={summaries}
              onChange={applyCommand}
            />
            <ImportCard
              mode={activeMode}
              busy={generating || importing}
              onFiles={addFiles}
            />
            <QueueCard
              jobs={jobs}
              logs={taskLogs}
              outputDir={completedOutputDir || outputDir}
              onOpenOutput={(path) => {
                void openOutput(path).catch((error) => {
                  setBanner(
                    `无法打开输出位置：${error instanceof Error ? error.message : error}`,
                  );
                });
              }}
              onClear={clearJobs}
              onRemove={removeJob}
              combinedMode={mergedBatch}
              busy={generating}
              onQuantityChange={(jobId, quantity) => {
                setJobs((current) => current.map((job) => (
                  job.id === jobId
                    ? { ...job, quantity, state: "ready", progress: 0 }
                    : job
                )));
                setCompletedOutputDir(null);
              }}
              onParameterSourceChange={(jobId, source) => {
                setJobs((current) => current.map((job) => (
                  job.id === jobId
                    ? {
                        ...job,
                        parameterSource: source,
                        state: "ready",
                        progress: 0,
                      }
                    : job
                )));
                setCompletedOutputDir(null);
              }}
              onReorder={(fromId, toId) => {
                setJobs((current) => {
                  const from = current.findIndex((job) => job.id === fromId);
                  const to = current.findIndex((job) => job.id === toId);
                  if (from < 0 || to < 0 || from === to) return current;
                  const next = [...current];
                  const [moving] = next.splice(from, 1);
                  next.splice(to, 0, moving);
                  return next;
                });
                setCompletedOutputDir(null);
              }}
            />
          </div>
          <SettingsPanel
            mode={activeMode}
            hasModels={canGenerate}
            busy={generating}
            settings={settings}
            machines={machines}
            materials={materials}
            recentKeys={recentKeys}
            actionHint={actionHint}
            outputDir={outputDir}
            onChange={updateSetting}
            onGenerate={generate}
            onCancel={stop}
            onOpenOutput={() => {
              void openOutput(outputDir).catch((error) => {
                setBanner(`无法打开输出目录：${error instanceof Error ? error.message : error}`);
              });
            }}
            onChooseOutput={() => {
              void chooseOutput()
                .then((result) => setOutputDir(result.path))
                .catch((error) => {
                  setBanner(`选择输出目录失败：${error instanceof Error ? error.message : error}`);
                });
            }}
          />
        </div>
          </>
        )}
      </main>

      <ImportPolicyDialog
        open={Boolean(pendingImport)}
        loading={Boolean(pendingImport?.loading)}
        imported={pendingImport?.imported ?? []}
        localNames={pendingImport?.localNames ?? []}
        issues={pendingImport?.issues ?? []}
        error={pendingImport?.error}
        settings={settings}
        onCancel={() => {
          if (pendingImport?.loading) return;
          setPendingImport(null);
          setBanner("已取消本次模型导入。");
        }}
        onConfirm={(policy) => {
          if (!pendingImport || pendingImport.loading || pendingImport.error) return;
          completeImport(pendingImport.imported, pendingImport.issues, policy);
          setPendingImport(null);
        }}
      />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
