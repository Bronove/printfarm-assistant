export type WorkspaceMode = "workbench" | "multicolor" | "figurine" | "batch";

export type JobState = "ready" | "grouped" | "printing" | "done" | "error";

export interface FileParameterSummary {
  hasEmbeddedSettings: boolean;
  layerHeight?: string;
  infill?: string;
  pattern?: string;
  supportEnabled?: boolean;
  supportType?: string;
  supportPlateOnly?: boolean;
  material?: string;
}

export type ParameterSourceMode = "file" | "habit" | "custom";
export type OverridableParameter = "layerHeight" | "infill" | "pattern" | "support";

export interface ImportParameterPolicy {
  mode: ParameterSourceMode;
  overrides: Record<OverridableParameter, boolean>;
}

export interface ModelJob {
  id: string;
  name: string;
  sizeLabel: string;
  material: string;
  color: string;
  state: JobState;
  serverPath?: string;
  previewUrl?: string;
  outputDir?: string;
  progress?: number;
  error?: string;
  quantity?: string;
  parameterSource?: "file" | "current";
  mergeParts?: number;
  mergeIssue?: string;
}

export interface ModeDefinition {
  id: WorkspaceMode;
  label: string;
  description: string;
}

export type SupportMode =
  | "off"
  | "tree_plate"
  | "tree_all"
  | "normal_plate"
  | "normal_all";
export type InfillPattern = "grid" | "lines" | "gyroid" | "honeycomb" | "cubic";
export type MulticolorStrategy = "zero_flush" | "fewer_plates" | "time_budget";

export interface SliceSettings {
  printer: string;
  material: string;
  bedType: string;
  layerHeight: string;
  infill: string;
  pattern: InfillPattern;
  supportMode: SupportMode;
  autoArrange: boolean;
  orientation: boolean;
  tightPacking: boolean;
  minSupport: boolean;
  clone: string;
  outputMode: "gcode" | "3mf";
  maxColors: string;
  multicolorStrategy: MulticolorStrategy;
  targetHours: string;
  hideSeam: boolean;
  topIroning: boolean;
  batchOutputMode?: "separate" | "combined";
  supportOverlap?: boolean;
  batchItems?: BatchMergeItem[];
  parameterPolicy?: ImportParameterPolicy;
}

export interface BatchMergeItem {
  path: string;
  quantity: number;
  parameterSource: "file" | "current";
}
