export type WorkspaceMode = "workbench" | "batch";

export type JobState = "ready" | "grouped" | "printing" | "done" | "error";

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
  hideSeam: boolean;
  topIroning: boolean;
}
