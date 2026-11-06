import { useRef, useState } from "react";
import type { ModelJob } from "../types";
import { STATE_LABELS } from "../data";
import {
  CheckIcon,
  FileTextIcon,
  FolderIcon,
  SparkIcon,
  TrashIcon,
} from "./ui/icons";

export default function QueueCard({
  jobs,
  logs,
  outputDir,
  onOpenOutput,
  onClear,
  onRemove,
  combinedMode = false,
  busy = false,
  onQuantityChange,
  onParameterSourceChange,
  onReorder,
}: {
  jobs: ModelJob[];
  logs: string[];
  outputDir: string;
  onOpenOutput: (path: string) => void;
  onClear: () => void;
  onRemove: (jobId: string) => void;
  combinedMode?: boolean;
  busy?: boolean;
  onQuantityChange?: (jobId: string, quantity: string) => void;
  onParameterSourceChange?: (jobId: string, source: "file" | "current") => void;
  onReorder?: (fromId: string, toId: string) => void;
}) {
  const draggingId = useRef<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const totalCopies = jobs.reduce(
    (total, job) => total + Math.max(1, Number(job.quantity || 1)),
    0,
  );

  return (
    <section className="panel queue-panel" aria-labelledby="queue-title">
      <div className="panel-heading">
        <div>
          <h2 id="queue-title">任务队列</h2>
          <p>
            {jobs.length
              ? combinedMode
                ? `${jobs.length} 个文件 · ${totalCopies} 份打印`
                : `${jobs.length} 个零件 · ${new Set(jobs.map((job) => job.material)).size} 种材料`
              : "还没有加入模型"}
          </p>
        </div>
        {jobs.length ? (
          <button
            className="text-button"
            type="button"
            disabled={busy}
            onClick={onClear}
          >
            清空
          </button>
        ) : null}
      </div>

      {jobs.length ? (
        <div className="queue-list">
          {jobs.map((job) => (
            <article
              className={`queue-item${combinedMode ? " queue-item--merge" : ""}${dragging === job.id ? " is-dragging" : ""}`}
              key={job.id}
              draggable={combinedMode && !busy}
              onDragStart={() => {
                draggingId.current = job.id;
                setDragging(job.id);
              }}
              onDragEnd={() => {
                draggingId.current = null;
                setDragging(null);
              }}
              onDragOver={(event) => {
                if (combinedMode) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                const fromId = draggingId.current;
                draggingId.current = null;
                setDragging(null);
                if (fromId && fromId !== job.id) onReorder?.(fromId, job.id);
              }}
            >
              {combinedMode ? (
                <span className="queue-item__grip" aria-hidden="true">
                  <i /><i /><i />
                </span>
              ) : null}
              <span
                className="queue-item__preview"
                style={{
                  "--swatch": job.color.startsWith("#") ? job.color : "#a8b0ac",
                } as React.CSSProperties}
                aria-label={job.previewUrl ? `${job.name} 缩略图` : "模型缩略图"}
              >
                {job.previewUrl ? (
                  <img src={job.previewUrl} alt="" />
                ) : (
                  <FileTextIcon aria-hidden="true" />
                )}
                <span className="material-swatch" aria-hidden="true" />
              </span>
              <span className="queue-item__main">
                <strong>{job.name}</strong>
                <span>
                  {job.sizeLabel}
                  {job.mergeParts
                    ? ` · 拆件后 ${job.mergeParts} Part`
                    : ""}
                </span>
              </span>
              <span className="queue-item__material">
                {job.material}
                {job.color && !job.color.startsWith("#") ? ` · ${job.color}` : ""}
              </span>
              {combinedMode ? (
                <label className="queue-quantity" title="整套文件打印数量">
                  <span>份</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={999}
                    value={job.quantity || "1"}
                    disabled={busy}
                    aria-label={`${job.name} 打印数量`}
                    onChange={(event) => onQuantityChange?.(job.id, event.target.value)}
                  />
                </label>
              ) : null}
              {combinedMode ? (
                <select
                  className="queue-parameter-source"
                  aria-label={`${job.name} 参数来源`}
                  value={job.parameterSource || "file"}
                  disabled={busy}
                  onChange={(event) => onParameterSourceChange?.(
                    job.id,
                    event.target.value as "file" | "current",
                  )}
                >
                  <option value="file">跟随文件</option>
                  <option value="current">当前设置</option>
                </select>
              ) : null}
              <span className="queue-item__actions">
                <span className={`job-state job-state--${job.state}`}>
                  {job.state === "grouped" ? <SparkIcon /> : null}
                  {job.state === "done" ? <CheckIcon /> : null}
                  {STATE_LABELS[job.state]}
                </span>
                {job.state === "done" ? (
                  <button
                    className="text-button queue-item__open"
                    type="button"
                    onClick={() => onOpenOutput(job.outputDir || outputDir)}
                  >
                    <FolderIcon />
                    打开所在位置
                  </button>
                ) : null}
                <button
                  className="icon-button queue-item__remove"
                  type="button"
                  disabled={busy}
                  aria-label={`从队列移除 ${job.name}`}
                  title="从队列移除（不会删除源文件）"
                  onClick={() => onRemove(job.id)}
                >
                  <TrashIcon />
                </button>
              </span>
              {job.progress !== undefined && job.state === "printing" ? (
                <span className="job-progress" aria-label={`切片进度 ${job.progress}%`}>
                  <span style={{ width: `${job.progress}%` }} />
                </span>
              ) : null}
              {job.error ? (
                <span className="job-error" role="status">{job.error}</span>
              ) : null}
              {job.mergeIssue ? (
                <span className="job-error" role="status">{job.mergeIssue}</span>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <span className="empty-state__mark" aria-hidden="true">
            <SparkIcon />
          </span>
          <strong>导入模型后在这里检查分组</strong>
          <p>同色零件会集中到同一组；有疑问的零件会在开始前单独标出。</p>
          <button
            type="button"
            className="text-button"
            onClick={() => window.dispatchEvent(new CustomEvent("load-demo-jobs"))}
          >
            载入演示模型
          </button>
        </div>
      )}

      {logs.length ? (
        <details className="run-log">
          <summary>运行日志 · {logs.length} 条</summary>
          <pre>{logs.join("\n")}</pre>
        </details>
      ) : null}
    </section>
  );
}
