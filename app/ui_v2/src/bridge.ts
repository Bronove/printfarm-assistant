import type { SliceSettings, WorkspaceMode } from "./types";

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

function fileData(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error(`无法读取 ${file.name}`));
    reader.readAsDataURL(file);
  });
}

export async function getBridgeConfig() {
  return request<BridgeConfig & { ok: true }>("/api/config");
}

export async function uploadModels(files: File[]) {
  const encoded = [];
  for (const file of files) {
    encoded.push({
      name: file.name,
      relativePath: file.webkitRelativePath || file.name,
      data: await fileData(file),
    });
  }
  return request<{
    ok: true;
    jobs: BridgeImportedFile[];
    issues?: string[];
  }>("/api/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: encoded }),
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
}: {
  mode: WorkspaceMode;
  models: string[];
  settings: SliceSettings;
  command: string;
  outputDir: string;
}) {
  return request<{ ok: true; taskId: string } & BridgeState>("/api/slice", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, models, settings, command, outputDir }),
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
