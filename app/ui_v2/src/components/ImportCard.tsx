import { useRef, useState } from "react";
import Button from "./ui/Button";
import { UploadIcon } from "./ui/icons";
import type { WorkspaceMode } from "../types";

const COPY: Record<WorkspaceMode, {
  title: string;
  description: string;
  strong: string;
  hint: string;
  action: string;
}> = {
  workbench: {
    title: "选择简单文件",
    description: "适合单个模型或已经整理好的 3MF；保留原朝向，直接进入切片。",
    strong: "拖入一个或多个模型",
    hint: "工作台不会主动拆件重排，适合简单、已经确认过摆放的文件。",
    action: "选择文件",
  },
  batch: {
    title: "准备批量文件",
    description: "一次加入多个简单模型，按相同参数连续切片。",
    strong: "把一批模型拖到这里",
    hint: "同目录文件会按相同配方处理，有问题的文件会单独列出。",
    action: "选择文件夹",
  },
};

export default function ImportCard({
  mode,
  onFiles,
}: {
  mode: WorkspaceMode;
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const copy = COPY[mode];

  const acceptFiles = (files: FileList | null) => {
    if (!files?.length) return;
    onFiles(Array.from(files));
  };

  return (
    <section className="panel import-panel" aria-labelledby="import-title">
      <div className="panel-heading">
        <div>
          <h2 id="import-title">{copy.title}</h2>
          <p>{copy.description}</p>
        </div>
        <span className="panel-kicker">第 1 步</span>
      </div>

      <div
        className={`drop-well${dragging ? " is-dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setDragging(false);
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          acceptFiles(event.dataTransfer.files);
        }}
      >
        <span className="drop-well__icon" aria-hidden="true">
          <UploadIcon />
        </span>
        <div className="drop-well__copy">
          <strong>{copy.strong}</strong>
          <span>{copy.hint}</span>
        </div>
        <Button
          leadingIcon={<UploadIcon />}
          onClick={() => inputRef.current?.click()}
        >
          {copy.action}
        </Button>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          multiple
          {...(mode === "batch"
            ? ({ webkitdirectory: "", directory: "" } as Record<string, string>)
            : {})}
          accept=".stl,.3mf,.step,.stp"
          onChange={(event) => {
            acceptFiles(event.target.files);
            event.currentTarget.value = "";
          }}
        />
      </div>
    </section>
  );
}
