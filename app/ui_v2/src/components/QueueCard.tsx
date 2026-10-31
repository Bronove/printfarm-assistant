import type { ModelJob } from "../types";
import { STATE_LABELS } from "../data";
import { CheckIcon, FileTextIcon, FolderIcon, SparkIcon } from "./ui/icons";

export default function QueueCard({
  jobs,
  logs,
  outputDir,
  onOpenOutput,
  onClear,
}: {
  jobs: ModelJob[];
  logs: string[];
  outputDir: string;
  onOpenOutput: (path: string) => void;
  onClear: () => void;
}) {
  return (
    <section className="panel queue-panel" aria-labelledby="queue-title">
      <div className="panel-heading">
        <div>
          <h2 id="queue-title">任务队列</h2>
          <p>
            {jobs.length
              ? `${jobs.length} 个零件 · ${new Set(jobs.map((job) => job.material)).size} 种材料`
              : "还没有加入模型"}
          </p>
        </div>
        {jobs.length ? (
          <button className="text-button" type="button" onClick={onClear}>
            清空
          </button>
        ) : null}
      </div>

      {jobs.length ? (
        <div className="queue-list">
          {jobs.map((job) => (
            <article className="queue-item" key={job.id}>
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
                <span>{job.sizeLabel}</span>
              </span>
              <span className="queue-item__material">
                {job.material}
                {job.color && !job.color.startsWith("#") ? ` · ${job.color}` : ""}
              </span>
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
              {job.progress !== undefined && job.state === "printing" ? (
                <span className="job-progress" aria-label={`切片进度 ${job.progress}%`}>
                  <span style={{ width: `${job.progress}%` }} />
                </span>
              ) : null}
              {job.error ? (
                <span className="job-error" role="status">{job.error}</span>
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
