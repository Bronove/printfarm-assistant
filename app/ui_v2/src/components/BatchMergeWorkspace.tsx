import { useRef, useState } from "react";
import type {
  InfillPattern,
  ModelJob,
  SliceSettings,
  SupportMode,
} from "../types";
import Button from "./ui/Button";
import NumberField from "./ui/NumberField";
import {
  CheckIcon,
  FileTextIcon,
  FolderIcon,
  LayersIcon,
  MinusIcon,
  PlusIcon,
  TrashIcon,
  UploadIcon,
} from "./ui/icons";

const BEDS = [
  ["Textured PEI Plate", "纹理 PEI"],
  ["Cool Plate", "冷却板"],
  ["High Temp Plate", "高温板"],
  ["Engineering Plate", "工程板"],
] as const;

const SUPPORT_OPTIONS: Array<{ value: SupportMode; label: string }> = [
  { value: "tree_plate", label: "树状支撑 · 仅打印板" },
  { value: "tree_all", label: "树状支撑 · 全模型" },
  { value: "normal_plate", label: "普通支撑 · 仅打印板" },
  { value: "normal_all", label: "普通支撑 · 全模型" },
  { value: "off", label: "不生成支撑" },
];

const PATTERN_OPTIONS: Array<{ value: InfillPattern; label: string }> = [
  { value: "grid", label: "网格" },
  { value: "lines", label: "直线" },
  { value: "gyroid", label: "螺旋" },
  { value: "honeycomb", label: "蜂窝" },
  { value: "cubic", label: "立方体" },
];

function shortMachine(value: string) {
  return value.replace(/^Bambu Lab\s+/i, "").replace(/\s+0\.\d+\s+nozzle$/i, "");
}

function quantityValue(job: ModelJob) {
  const parsed = Number(job.quantity || 1);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(999, Math.round(parsed))) : 1;
}

function colorCount(job: ModelJob) {
  const match = job.material.match(/(\d+)\s*色/);
  return match ? Number(match[1]) : 1;
}

function fileType(job: ModelJob) {
  const path = job.serverPath || job.name;
  const match = path.match(/\.([a-z0-9]+)$/i);
  return match ? match[1].toUpperCase() : "模型";
}

export default function BatchMergeWorkspace({
  jobs,
  settings,
  machines,
  materials,
  outputDir,
  busy,
  importing,
  statusMessage,
  onFiles,
  onSettingChange,
  onQuantityChange,
  onReorder,
  onRemove,
  onClear,
  onGenerate,
  onCancel,
  onOpenOutput,
  onChooseOutput,
}: {
  jobs: ModelJob[];
  settings: SliceSettings;
  machines: string[];
  materials: string[];
  outputDir: string;
  busy: boolean;
  importing: boolean;
  statusMessage: string;
  onFiles: (files: File[]) => void;
  onSettingChange: <K extends keyof SliceSettings>(
    key: K,
    value: SliceSettings[K],
  ) => void;
  onQuantityChange: (jobId: string, quantity: string) => void;
  onReorder: (fromId: string, toId: string) => void;
  onRemove: (jobId: string) => void;
  onClear: () => void;
  onGenerate: () => void;
  onCancel: () => void;
  onOpenOutput: () => void;
  onChooseOutput: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const draggingId = useRef<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const totalCopies = jobs.reduce(
    (total, job) => total + quantityValue(job),
    0,
  );
  const totalParts = jobs.reduce(
    (total, job) => (
      total + Math.max(1, job.mergeParts || 1) * quantityValue(job)
    ),
    0,
  );
  const blockingJob = jobs.find((job) => job.mergeIssue);
  const printerOptions = machines.map((machine) => ({
    value: machine,
    label: shortMachine(machine),
  }));
  if (!printerOptions.some((option) => option.value === settings.printer)) {
    printerOptions.unshift({
      value: settings.printer,
      label: shortMachine(settings.printer),
    });
  }
  const bedOptions: Array<{ value: string; label: string }> = BEDS.map(
    ([value, label]) => ({ value, label }),
  );
  if (!bedOptions.some((option) => option.value === settings.bedType)) {
    bedOptions.unshift({ value: settings.bedType, label: settings.bedType });
  }
  const loading = importing || busy;
  const announcement = (
    !loading
    && /切片完成|排盘完成|失败|无法|已取消|部分文件|没有生成|需要处理|已导入|注意/.test(statusMessage)
  );
  const statusIsError = (
    !loading
    && /失败|无法|已取消|没有生成|需要处理/.test(statusMessage)
  );
  const status = loading
    ? statusMessage || (importing ? "正在导入模型…" : "正在处理…")
    : announcement
      ? statusMessage
        .replace(/已导入\s*(\d+)\s*个模型，可以开始切片。?/, "$1 个文件已导入")
        .replace(/，输出目录：.*$/s, "")
    : jobs.length
      ? `${jobs.length} 个文件已导入`
      : "等待添加模型";
  const completedPlates = statusMessage.match(/共\s*(\d+)\s*盘/)?.[1];
  const plateSummary = completedPlates
    ?? (busy ? "计算中" : jobs.length ? "自动" : "—");
  const canChooseFiles = !loading;

  const acceptFiles = (files: FileList | null) => {
    if (canChooseFiles && files?.length) onFiles(Array.from(files));
  };

  const stepQuantity = (job: ModelJob, delta: number) => {
    const next = Math.max(1, Math.min(999, quantityValue(job) + delta));
    onQuantityChange(job.id, String(next));
  };

  return (
    <section className="batch-workspace" aria-labelledby="batch-layout-title">
      <header className="batch-workspace__hero">
        <div>
          <h1 id="batch-layout-title">多文件合盘排布</h1>
          <p>导入不同模型，为每个文件设置打印份数，助手统一分盘并生成可在 Bambu Studio 继续编辑的多盘工程。</p>
        </div>
        <span
          className={`batch-import-state${loading ? " is-loading" : ""}${announcement ? " has-message" : ""}${statusIsError ? " is-error" : ""}`}
          role="status"
          aria-busy={loading || undefined}
          title={statusMessage}
        >
          <i aria-hidden="true" />
          <span>{status}</span>
          {loading ? (
            <span
              className="status-banner__spinner"
              role="status"
              aria-label="正在处理"
            />
          ) : null}
        </span>
      </header>

      <div className="batch-workspace__grid">
        <section className="batch-files-card">
          <header className="batch-files-card__heading">
            <div>
              <h2>打印文件与数量</h2>
              <p>每行代表一个源文件；数量按整套复制，文件内零件、颜色和朝向保持完整。</p>
            </div>
            <span className="batch-files-card__heading-actions">
              <span className="batch-count-chip">
                <LayersIcon />
                {completedPlates
                  ? `${completedPlates} 盘`
                  : busy
                    ? "盘数计算中"
                    : "盘数自动计算"}
              </span>
              {jobs.length ? (
                <button
                  className="text-button"
                  type="button"
                  disabled={loading}
                  onClick={onClear}
                >
                  清空
                </button>
              ) : null}
            </span>
          </header>

          <div
            className={`batch-drop${dropActive ? " is-dragging" : ""}${jobs.length ? "" : " is-empty"}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setDropActive(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setDropActive(false);
              }
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDropActive(false);
              acceptFiles(event.dataTransfer.files);
            }}
          >
            <span className="batch-drop__icon" aria-hidden="true">
              <UploadIcon />
            </span>
            <span className="batch-drop__copy">
              <strong>{jobs.length ? "继续添加模型文件" : "选择或拖入模型文件"}</strong>
              <span>支持 STL、3MF、STEP · 单次最多 10 个不同文件</span>
            </span>
            <span className="batch-drop__actions">
              <Button
                type="button"
                disabled={!canChooseFiles}
                onClick={() => fileInputRef.current?.click()}
              >
                选择文件
              </Button>
              <button
                className="text-button batch-drop__folder"
                type="button"
                disabled={!canChooseFiles}
                onClick={() => folderInputRef.current?.click()}
              >
                或选择文件夹
              </button>
            </span>
            <input
              ref={fileInputRef}
              className="visually-hidden"
              type="file"
              disabled={!canChooseFiles}
              multiple
              accept=".stl,.3mf,.step,.stp"
              onChange={(event) => {
                acceptFiles(event.target.files);
                event.currentTarget.value = "";
              }}
            />
            <input
              ref={folderInputRef}
              className="visually-hidden"
              type="file"
              disabled={!canChooseFiles}
              multiple
              accept=".stl,.3mf,.step,.stp"
              {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
              onChange={(event) => {
                acceptFiles(event.target.files);
                event.currentTarget.value = "";
              }}
            />
          </div>

          {jobs.length ? (
            <div className="batch-file-table">
              <div className="batch-file-table__head" aria-hidden="true">
                <span>文件与参数</span>
                <span>打印份数</span>
                <span />
              </div>
              <div className="batch-file-table__body">
                {jobs.map((job) => {
                  const count = colorCount(job);
                  const type = fileType(job);
                  const swatch = job.color.startsWith("#")
                    ? job.color
                    : count > 1
                      ? "#c69452"
                      : "#9aa6a0";
                  return (
                    <article
                      className={`batch-file-row${dragging === job.id ? " is-dragging" : ""}${dropTarget === job.id ? " is-drop-target" : ""}`}
                      key={job.id}
                      draggable={!loading}
                      onDragStart={() => {
                        if (loading) return;
                        draggingId.current = job.id;
                        setDragging(job.id);
                      }}
                      onDragEnd={() => {
                        draggingId.current = null;
                        setDragging(null);
                        setDropTarget(null);
                      }}
                      onDragOver={(event) => event.preventDefault()}
                      onDragEnter={() => {
                        if (draggingId.current && draggingId.current !== job.id) {
                          setDropTarget(job.id);
                        }
                      }}
                      onDragLeave={(event) => {
                        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                          setDropTarget((current) => current === job.id ? null : current);
                        }
                      }}
                      onDrop={(event) => {
                        event.preventDefault();
                        const fromId = draggingId.current;
                        draggingId.current = null;
                        setDragging(null);
                        setDropTarget(null);
                        if (fromId && fromId !== job.id) onReorder(fromId, job.id);
                      }}
                    >
                      <span className="batch-file-row__grip" aria-hidden="true">
                        <i /><i /><i />
                      </span>
                      <div className="batch-file-row__file">
                        <span
                          className="batch-file-row__thumb"
                          style={{ "--swatch": swatch } as React.CSSProperties}
                          aria-hidden="true"
                        >
                          {job.previewUrl ? (
                            <img src={job.previewUrl} alt="" />
                          ) : (
                            <FileTextIcon />
                          )}
                        </span>
                        <span className="batch-file-row__copy">
                          <span className="batch-file-row__title">
                            <strong title={job.name}>{job.name}</strong>
                            {busy && job.state === "printing" ? (
                              <span className="batch-file-row__state is-running">
                                {Math.round(job.progress || 0)}%
                              </span>
                            ) : job.state === "done" ? (
                              <span className="batch-file-row__state is-done">
                                <CheckIcon />
                                已完成
                              </span>
                            ) : job.state === "error" || job.mergeIssue ? (
                              <span className="batch-file-row__state is-error">
                                需处理
                              </span>
                            ) : null}
                          </span>
                          <span className="batch-file-row__meta">
                            <span>{type}</span>
                            <span>
                              <i style={{ background: swatch }} aria-hidden="true" />
                              {count} 色
                            </span>
                            <span>{job.sizeLabel}</span>
                            {job.mergeParts && job.mergeParts > 1
                              ? <span>拆件后 {job.mergeParts} Part</span>
                              : null}
                          </span>
                          {job.mergeIssue ? (
                            <span className="batch-file-row__issue">
                              {job.mergeIssue}
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <span className="batch-quantity">
                        <button
                          type="button"
                          aria-label={`减少 ${job.name} 数量`}
                          disabled={loading || quantityValue(job) <= 1}
                          onClick={() => stepQuantity(job, -1)}
                        >
                          <MinusIcon />
                        </button>
                        <input
                          type="number"
                          inputMode="numeric"
                          step={1}
                          min={1}
                          max={999}
                          value={job.quantity || "1"}
                          disabled={loading}
                          aria-label={`${job.name} 打印数量`}
                          onChange={(event) => onQuantityChange(
                            job.id,
                            event.target.value,
                          )}
                        />
                        <button
                          type="button"
                          aria-label={`增加 ${job.name} 数量`}
                          disabled={loading || quantityValue(job) >= 999}
                          onClick={() => stepQuantity(job, 1)}
                        >
                          <PlusIcon />
                        </button>
                      </span>
                      <button
                        className="icon-button batch-file-row__remove"
                        type="button"
                        disabled={loading}
                        aria-label={`从队列移除 ${job.name}`}
                        title="从队列移除（不会删除源文件）"
                        onClick={() => onRemove(job.id)}
                      >
                        <TrashIcon />
                      </button>
                    </article>
                  );
                })}
              </div>
            </div>
          ) : null}

          <footer className="batch-merge-summary">
            <div className="batch-merge-summary__copy">
              <strong>
                {jobs.length
                  ? importing
                    ? "正在读取文件数量、颜色和参数"
                    : `将 ${jobs.length} 个文件合并为一个可编辑工程`
                  : "添加文件后自动汇总"}
              </strong>
              <span>
                {blockingJob
                  ? `${blockingJob.name}：${blockingJob.mergeIssue}`
                  : "按机型、当前参数和文件数量自动分盘，生成后仍可在 Bambu 中调整对象与盘面。"}
              </span>
            </div>
            <div className="batch-merge-summary__stats">
              <span><strong>{jobs.length}</strong><small>文件</small></span>
              <span><strong>{totalCopies}</strong><small>打印份数</small></span>
              <span><strong>{totalParts}</strong><small>展开零件</small></span>
              <span><strong>{plateSummary}</strong><small>盘数</small></span>
            </div>
            <Button
              variant="primary"
              disabled={busy ? false : !jobs.length || Boolean(blockingJob) || importing}
              onClick={busy ? onCancel : onGenerate}
              title={blockingJob?.mergeIssue}
            >
              {busy
                ? "停止切片"
                : importing
                  ? "正在导入…"
                  : blockingJob
                    ? "请先处理文件"
                    : "生成可编辑 3MF"}
            </Button>
          </footer>
        </section>

        <aside className="batch-rules" aria-labelledby="batch-rules-title">
          <div className="batch-rules__heading">
            <h2 id="batch-rules-title">本次排盘规则</h2>
            <span>修改后立即应用到整批</span>
          </div>

          <label className="batch-rule-field">
            <span>打印机</span>
            <select
              aria-label="打印机"
              value={settings.printer}
              disabled={loading}
              onChange={(event) => {
                onSettingChange("printer", event.target.value);
              }}
            >
              {printerOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="batch-rule-field">
            <span>打印板</span>
            <select
              aria-label="打印板"
              value={settings.bedType}
              disabled={loading}
              onChange={(event) => onSettingChange("bedType", event.target.value)}
            >
              {bedOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <div className="batch-rule-divider" />

          <div className="batch-rule-readonly">
            <span>输出格式</span>
            <strong>可编辑多盘 .3mf</strong>
          </div>

          <div className="batch-delivery">
            <span className="batch-delivery__icon" aria-hidden="true">
              <LayersIcon />
            </span>
            <span>
              <small>交付形式</small>
              <strong>通用 .3mf 工程</strong>
              <em>保留独立对象、颜色和盘面，可在 Bambu Studio 修改后重新切片</em>
            </span>
          </div>

          <p className="batch-rules__note">
            只排列对象并导出工程，不切片、不保存 G-code。当前合并排盘只处理单色模型。
          </p>

          <details className="batch-advanced">
            <summary>
              工艺参数
              <span>{settings.layerHeight} mm · {settings.infill}%</span>
            </summary>
            <div className="batch-advanced__body">
              <NumberField
                label="层高"
                value={settings.layerHeight}
                suffix="mm"
                min={0.04}
                max={1}
                step={0.01}
                disabled={loading}
                onChange={(value) => onSettingChange("layerHeight", value)}
              />
              <NumberField
                label="填充"
                value={settings.infill}
                suffix="%"
                min={0}
                max={100}
                step={1}
                disabled={loading}
                onChange={(value) => onSettingChange("infill", value)}
              />
              <label className="batch-rule-field">
                <span>填充图案</span>
                <select
                  aria-label="填充图案"
                  value={settings.pattern}
                  disabled={loading}
                  onChange={(event) => onSettingChange(
                    "pattern",
                    event.target.value as InfillPattern,
                  )}
                >
                  {PATTERN_OPTIONS.map((option) => (
                    <option value={option.value} key={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="batch-rule-field">
                <span>支撑</span>
                <select
                  aria-label="支撑"
                  value={settings.supportMode}
                  disabled={loading}
                  onChange={(event) => onSettingChange(
                    "supportMode",
                    event.target.value as SupportMode,
                  )}
                >
                  {SUPPORT_OPTIONS.map((option) => (
                    <option value={option.value} key={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="batch-rule-field">
                <span>耗材</span>
                <select
                  aria-label="耗材"
                  value={settings.material}
                  disabled={loading}
                  onChange={(event) => onSettingChange("material", event.target.value)}
                >
                  {materials.map((material) => (
                    <option value={material} key={material}>{material}</option>
                  ))}
                </select>
              </label>
            </div>
          </details>

          <div className="batch-output-path">
            <button type="button" onClick={onOpenOutput}>
              <FolderIcon />
              <span title={outputDir}>{outputDir}</span>
            </button>
            <button
              className="text-button"
              type="button"
              disabled={loading}
              onClick={onChooseOutput}
            >
              更改
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}
