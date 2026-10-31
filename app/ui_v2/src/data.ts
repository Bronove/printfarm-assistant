import type { ModeDefinition, ModelJob } from "./types";

export const MODES: ModeDefinition[] = [
  {
    id: "workbench",
    label: "切片工作台",
    description: "按原始朝向切片，适合已经整理好的单个模型。",
  },
  {
    id: "batch",
    label: "批量切片",
    description: "扫描文件夹并连续生成可直接打印的工程文件。",
  },
];

export const DEMO_JOBS: ModelJob[] = [
  {
    id: "demo-1",
    name: "底座_A.stl",
    sizeLabel: "86 × 44 × 12 mm",
    material: "PLA",
    color: "暖灰",
    state: "grouped",
  },
  {
    id: "demo-2",
    name: "外壳_左侧.stl",
    sizeLabel: "103 × 62 × 28 mm",
    material: "PLA",
    color: "暖灰",
    state: "grouped",
  },
  {
    id: "demo-3",
    name: "旋钮_B.stl",
    sizeLabel: "32 × 32 × 18 mm",
    material: "PLA",
    color: "棕色",
    state: "ready",
  },
  {
    id: "demo-4",
    name: "盖板.stl",
    sizeLabel: "91 × 58 × 6 mm",
    material: "PLA",
    color: "暖灰",
    state: "ready",
  },
];

export const STATE_LABELS = {
  ready: "待排盘",
  grouped: "已分组",
  printing: "切片中",
  done: "已完成",
  error: "需要处理",
} as const;
