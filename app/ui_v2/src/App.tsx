import { useEffect, useMemo, useRef, useState } from "react";
import AppHeader from "./components/AppHeader";
import ImportCard from "./components/ImportCard";
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
  startSliceJob,
  uploadModels,
} from "./bridge";
import type { ModelJob, SliceSettings, WorkspaceMode } from "./types";
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
  hideSeam: false,
  topIroning: false,
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
      };
    });
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
  const [settingsOpen, setSettingsOpen] = useState(false);
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
  const actionHint = sliceableJobs.length
    ? activeMode === "workbench"
      ? `将对 ${sliceableJobs.length} 个简单文件按当前参数直接切片。`
      : `将按同一套参数连续处理 ${sliceableJobs.length} 个文件。`
    : jobs.length
      ? "当前是演示任务。导入真实模型后才能启动切片。"
    : activeMode === "workbench"
      ? "先导入简单文件，工作台会保留当前朝向直接切片。"
      : "先选择模型文件夹，再按同一套参数连续切片。";

  const applyCommand = (value: string) => {
    setCommand(value);
    const parsed = parseParameterCommand(value);
    setSettings((current) => ({ ...current, ...parsed.patch }));
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
          setTaskLogs(task.logs);
          setJobs((current) => current.map((job) => {
            if (!job.serverPath) return job;
            if (task.status === "done") {
              return {
                ...job,
                state: "done",
                progress: 100,
                error: undefined,
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
            setBanner(`切片完成，输出目录：${task.outputDir || outputDir}`);
          } else if (task.status === "cancelled") {
            setCompletedOutputDir(null);
            setBanner("切片已取消。");
          } else {
            setBanner(`切片失败：${task.message}`);
          }
        })
        .catch((error) => {
          if (disposed) return;
          setGenerating(false);
          setBanner(`无法读取切片状态：${error instanceof Error ? error.message : error}`);
        });
    }, 650);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [generating, outputDir]);

  useEffect(() => {
    const loadDemo = () => {
      setJobs(DEMO_JOBS);
      setBanner("已重新载入演示模型。");
    };
    window.addEventListener("load-demo-jobs", loadDemo);
    return () => window.removeEventListener("load-demo-jobs", loadDemo);
  }, []);

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
    const unique = next.filter((job) => !known.has(job.id));
    if (unique.length) setJobs((current) => [...current, ...unique]);
    setBanner(
      unique.length
        ? `正在导入 ${unique.length} 个模型文件…`
        : "这些模型已经在任务队列里。",
    );
    if (!unique.length) return;
    const insertedIds = new Set(unique.map((job) => job.id));
    void uploadModels(files)
      .then((result) => {
        const uploaded = result.jobs.map((item) => ({
          id: `server:${item.path}`,
          name: item.relativePath || item.name,
          sizeLabel: formatBytes(item.size),
          material: item.material || "待识别",
          color: item.color || "",
          state: "ready" as const,
          serverPath: item.path,
          previewUrl: item.preview,
        }));
        setJobs((current) => [
          ...current.filter((job) => !insertedIds.has(job.id)),
          ...uploaded,
        ]);
        setBanner(
          `已导入 ${uploaded.length} 个模型，可以开始切片。`
          + (result.issues?.length ? ` 注意：${result.issues.join("；")}` : ""),
        );
      })
      .catch((error) => {
        setJobs((current) => current.map((job) => (
          insertedIds.has(job.id)
            ? {
                ...job,
                state: "error",
                error: error instanceof Error ? error.message : String(error),
              }
            : job
        )));
        setBanner(`模型导入失败：${error instanceof Error ? error.message : error}`);
      });
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

  return (
    <div className="app-shell">
      <AppHeader
        modes={MODES}
        activeMode={activeMode}
        onModeChange={(mode) => {
          logLocal("界面", "切换工作模式", { mode });
          setActiveMode(mode);
        }}
        onSettingsOpen={() => {
          logLocal("设置", "打开软件设置");
          setSettingsOpen(true);
        }}
      />

      <main className="app-main">
        <section className="workspace-intro">
          <div>
            <h1>{activeDefinition.label}</h1>
            <p>{activeDefinition.description}</p>
          </div>
        </section>

        {banner ? (
          <StatusBanner
            tone="success"
            title="界面已就绪"
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
            <ImportCard mode={activeMode} onFiles={addFiles} />
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
              onClear={() => {
                setJobs([]);
                setTaskLogs([]);
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
            onChange={(key, value) => {
              setSettings((current) => {
                const next = { ...current, [key]: value };
                if (key === "outputMode" && value === "3mf") {
                  next.tightPacking = false;
                  next.minSupport = false;
                }
                return next;
              });
              setRecentKeys([key]);
            }}
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
      </main>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
