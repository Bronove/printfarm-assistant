import type {
  BatchMergeItem,
  FileParameterSummary,
  SliceSettings,
  WorkspaceMode,
} from "./types";

export interface BridgeConfig {
  machines: string[];
  materials: string[];
  machine: string;
  process: string;
  filament: string;
  bed: string;
  outputDir: string;
}

export interface BridgeImportedFile {
  path: string;
  name: string;
  relativePath?: string;
  size: number;
  material?: string;
  color?: string;
  preview?: string;
  fileSettings?: FileParameterSummary;
  mergeParts?: number;
  mergeIssue?: string;
}

export interface BridgeTask {
  id: string;
  status: "running" | "done" | "error" | "cancelled";
  progress: number;
  message: string;
  logs: string[];
  outputDir: string;
  startedAt: number;
  finishedAt: number | null;
  results?: Array<{
    file?: string;
    slice_checked?: boolean;
    support_verified?: boolean;
    total_actual_hours?: number | null;
    total_plates?: number;
    output_files?: string[];
    warnings?: string[];
    needs_attention?: boolean;
    layout_only?: boolean;
    layout_checked?: boolean;
    editable_file?: string;
    print_file?: string;
    plates?: Array<{
      name: string;
      actual_hours?: number | null;
      printTimeS?: number | null;
      outputPlate?: number;
    }>;
  }>;
}

export interface BridgeState {
  busy: boolean;
  task: BridgeTask | null;
}

export interface BridgeMeta {
  version: string;
  usage: {
    total: number;
    events: Array<[string, number]>;
    recent: Array<Record<string, unknown>>;
  };
  learning: {
    summary: string;
    phraseRules: Array<{
      norm: string;
      overrides: Record<string, unknown>;
      hits?: number;
      enabled?: boolean;
    }>;
    defaults: Record<string, unknown>;
    samples: number;
  };
}

const DEFAULT_BRIDGE = "http://127.0.0.1:4180";

function bridgeBase() {
  const endpoint = import.meta.env.VITE_OCR_ENDPOINT
    ?? `${DEFAULT_BRIDGE}/api/ocr`;
  try {
    return new URL(endpoint).origin;
  } catch {
    return DEFAULT_BRIDGE;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${bridgeBase()}${path}`, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `本机服务返回 ${response.status}`);
  }
  return payload as T;
}

function uploadModelFile(
  sessionId: string,
  file: File,
  onProgress?: (loaded: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const query = new URLSearchParams({
      session: sessionId,
      relativePath: file.webkitRelativePath || file.name,
    });
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${bridgeBase()}/api/import/file?${query.toString()}`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      onProgress?.(Math.min(event.loaded, file.size));
    };
    xhr.onload = () => {
      const payload = xhr.response ?? {};
      if (xhr.status >= 200 && xhr.status < 300 && payload.ok !== false) {
        onProgress?.(file.size);
        resolve();
        return;
      }
      reject(new Error(
        payload.error || `导入 ${file.name} 失败，本机服务返回 ${xhr.status}`,
      ));
    };
    xhr.onerror = () => reject(new Error(`导入 ${file.name} 时连接中断`));
    xhr.onabort = () => reject(new Error(`导入 ${file.name} 已取消`));
    onProgress?.(0);
    xhr.send(file);
  });
}

export async function getBridgeConfig() {
  return request<BridgeConfig & { ok: true }>("/api/config");
}

export async function uploadModels(
  files: File[],
  onProgress?: (progress: {
    fileName: string;
    fileIndex: number;
    fileCount: number;
    loadedBytes: number;
    totalBytes: number;
  }) => void,
) {
  const started = await request<{ ok: true; sessionId: string }>(
    "/api/import/start",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  let completedBytes = 0;
  for (const [index, file] of files.entries()) {
    await uploadModelFile(started.sessionId, file, (loaded) => {
      onProgress?.({
        fileName: file.name,
        fileIndex: index + 1,
        fileCount: files.length,
        loadedBytes: completedBytes + loaded,
        totalBytes,
      });
    });
    completedBytes += file.size;
  }
  return request<{
    ok: true;
    jobs: BridgeImportedFile[];
    issues?: string[];
  }>(`/api/import/finish?session=${encodeURIComponent(started.sessionId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export async function releaseUploads() {
  return request<{ ok: true; removed: number }>("/api/import/release", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export async function parseOnServer(text: string, models: string[]) {
  return request<{
    ok: true;
    overrides: Record<string, unknown>;
    parts: string[];
  }>("/api/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, models }),
  });
}

export async function startSliceJob({
  mode,
  models,
  settings,
  command,
  outputDir,
  batchItems,
}: {
  mode: WorkspaceMode;
  models: string[];
  settings: SliceSettings;
  command: string;
  outputDir: string;
  batchItems?: BatchMergeItem[];
}) {
  return request<{ ok: true; taskId: string } & BridgeState>("/api/slice", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode, models, settings, command, outputDir, batchItems,
    }),
  });
}

export async function getTaskState() {
  return request<{ ok: true } & BridgeState>("/api/state");
}

export async function cancelTask() {
  return request<{ ok: boolean } & BridgeState>("/api/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export async function openOutput(path: string) {
  return request<{ ok: true }>("/api/open-output", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

export async function chooseOutput() {
  return request<{ ok: true; path: string }>("/api/choose-output", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export async function getMetadata() {
  return request<{ ok: true } & BridgeMeta>("/api/meta");
}

export async function updateRule(
  action: "toggle" | "remove" | "clear" | "remove-default",
  norm = "",
  enabled = true,
) {
  return request<{ ok: true } & BridgeMeta>("/api/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, norm, enabled }),
  });
}

export async function getLocalLogs() {
  return request<{ ok: true; path: string; text: string }>("/api/logs");
}

export async function openLogDirectory() {
  return request<{ ok: true; path: string }>("/api/open-logs");
}
