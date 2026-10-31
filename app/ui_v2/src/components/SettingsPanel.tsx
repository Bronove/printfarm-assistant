import Button from "./ui/Button";
import MagicToolbox from "./MagicToolbox";
import NumberField from "./ui/NumberField";
import Switch from "./ui/Switch";
import { ChevronIcon, FolderIcon, PrinterIcon } from "./ui/icons";
import useSmoothWheel from "../hooks/useSmoothWheel";
import type { InfillPattern, SliceSettings, SupportMode, WorkspaceMode } from "../types";

export default function SettingsPanel({
  mode,
  hasModels,
  busy,
  settings,
  machines,
  materials,
  recentKeys,
  actionHint,
  outputDir,
  onChange,
  onGenerate,
  onCancel,
  onOpenOutput,
  onChooseOutput,
}: {
  mode: WorkspaceMode;
  hasModels: boolean;
  busy: boolean;
  settings: SliceSettings;
  machines: string[];
  materials: string[];
  recentKeys: Array<keyof SliceSettings>;
  actionHint: string;
  outputDir: string;
  onChange: <K extends keyof SliceSettings>(key: K, value: SliceSettings[K]) => void;
  onGenerate: () => void;
  onCancel: () => void;
  onOpenOutput: () => void;
  onChooseOutput: () => void;
}) {
  const scrollRef = useSmoothWheel<HTMLElement>();
  const actionLabel = busy
    ? "停止切片"
    : mode === "batch"
      ? "开始批量切片"
      : "开始切片";
  const supportOptions: Array<{ value: SupportMode; label: string }> = [
    { value: "tree_plate", label: "树状支撑（仅打印板生成）" },
    { value: "tree_all", label: "树状支撑（全模型生成）" },
    { value: "normal_plate", label: "普通支撑（仅打印板生成）" },
    { value: "normal_all", label: "普通支撑（全模型生成）" },
    { value: "off", label: "不生成支撑" },
  ];
  const patternOptions: Array<{ value: InfillPattern; label: string }> = [
    { value: "grid", label: "网格" },
    { value: "lines", label: "直线" },
    { value: "gyroid", label: "螺旋" },
    { value: "honeycomb", label: "蜂窝" },
    { value: "cubic", label: "立方体" },
  ];
  const canOptimizeGeometry = settings.outputMode === "gcode";

  return (
    <aside ref={scrollRef} className="settings-panel" aria-labelledby="settings-title">
      <div className="settings-panel__heading">
        <div>
          <span className="panel-kicker">第 2 步</span>
          <h2 id="settings-title">排盘参数</h2>
        </div>
        <span className="settings-panel__status">
          <span aria-hidden="true" /> 参数已就绪
        </span>
      </div>

      <div className="setting-group">
        <span className="setting-group__label">打印机</span>
        <label className={`select-field${recentKeys.includes("printer") ? " is-synced" : ""}`}>
          <span className="select-field__leading">
            <PrinterIcon />
          </span>
          <span className="select-field__select">
            <select
              aria-label="打印机"
              value={settings.printer}
              onChange={(event) => onChange("printer", event.target.value)}
            >
              {machines.map((machine) => (
                <option key={machine} value={machine}>{machine}</option>
              ))}
            </select>
          </span>
          <ChevronIcon />
        </label>
      </div>

      <div className="mode-note">
        <strong>{mode === "workbench" ? "简单文件流程" : "批量统一参数"}</strong>
        <span>{mode === "workbench"
          ? "不拆件、不主动重排，直接按当前朝向切片。"
          : "所有文件沿用右侧同一套参数连续切片。"}</span>
      </div>

      <div className="setting-group parameter-group">
        <span className="setting-group__label">切片参数</span>
        <div className="parameter-grid">
          <NumberField
            label="层高"
            value={settings.layerHeight}
            suffix="mm"
            min={0.04}
            max={1}
            step={0.01}
            highlighted={recentKeys.includes("layerHeight")}
            onChange={(value) => onChange("layerHeight", value)}
          />
          <NumberField
            label="填充"
            value={settings.infill}
            suffix="%"
            min={0}
            max={100}
            step={1}
            highlighted={recentKeys.includes("infill")}
            onChange={(value) => onChange("infill", value)}
          />
        </div>
        <label className={`parameter-select${recentKeys.includes("pattern") ? " is-synced" : ""}`}>
          <span>填充图案</span>
          <select
            value={settings.pattern}
            onChange={(event) => onChange("pattern", event.target.value as InfillPattern)}
          >
            {patternOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <div className={`support-field${recentKeys.includes("supportMode") ? " is-synced" : ""}`}>
          <span>支撑</span>
          <select
            aria-label="支撑方式"
            title={supportOptions.find((option) => option.value === settings.supportMode)?.label}
            value={settings.supportMode}
            onChange={(event) => onChange("supportMode", event.target.value as SupportMode)}
          >
            {supportOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
      </div>

      <MagicToolbox
        hideSeam={settings.hideSeam}
        topIroning={settings.topIroning}
        onChange={onChange}
      />

      <details className="advanced-settings" open>
        <summary>更多切片参数</summary>
        <div className="advanced-settings__body">
          <label className={`parameter-select${recentKeys.includes("material") ? " is-synced" : ""}`}>
            <span>耗材</span>
            <select
              aria-label="耗材"
              value={settings.material}
              onChange={(event) => onChange("material", event.target.value)}
            >
              {materials.map((material) => (
                <option key={material} value={material}>{material}</option>
              ))}
            </select>
          </label>
          <label className={`parameter-select${recentKeys.includes("bedType") ? " is-synced" : ""}`}>
            <span>打印板</span>
            <select
              aria-label="打印板"
              value={settings.bedType}
              onChange={(event) => onChange("bedType", event.target.value)}
            >
              <option value="Textured PEI Plate">纹理钢板</option>
              <option value="Cool Plate">冷却板</option>
              <option value="High Temp Plate">高温板</option>
              <option value="Engineering Plate">工程板</option>
            </select>
          </label>
          <label className={`parameter-select${recentKeys.includes("outputMode") ? " is-synced" : ""}`}>
            <span>输出</span>
            <select
              aria-label="输出类型"
              value={settings.outputMode}
              onChange={(event) => onChange("outputMode", event.target.value as "gcode" | "3mf")}
            >
              <option value="gcode">可直接打印 G-code 3MF</option>
              <option value="3mf">仅生成可编辑 3MF</option>
            </select>
          </label>
          <NumberField
            label="克隆数量"
            value={settings.clone}
            suffix="个"
            min={1}
            max={100}
            step={1}
            highlighted={recentKeys.includes("clone")}
            onChange={(value) => onChange("clone", value)}
          />
          <Switch
            checked={settings.tightPacking}
            onChange={(checked) => onChange("tightPacking", checked)}
            label="最省空间"
            description={canOptimizeGeometry
              ? "紧凑摆盘，优先减少盘数"
              : "需切换为可直接打印 G-code"}
            disabled={!canOptimizeGeometry}
          />
          <Switch
            checked={settings.minSupport}
            onChange={(checked) => onChange("minSupport", checked)}
            label="最少支撑"
            description={canOptimizeGeometry
              ? "多比较方向，耗时更长"
              : "需切换为可直接打印 G-code"}
            disabled={!canOptimizeGeometry}
          />
        </div>
      </details>

      <div className="setting-group setting-group--well">
        <Switch
          checked={settings.autoArrange}
          onChange={(checked) => onChange("autoArrange", checked)}
          label="交给 Bambu 自动排列"
          description="助手先固定稳定朝向"
          help="助手先把稳定的大面朝下，再由 Bambu 摆放；已经整理好的整盘工程建议关闭。"
        />
        <span className="setting-divider" />
        <Switch
          checked={settings.orientation}
          onChange={(checked) => onChange("orientation", checked)}
          label="自动定向"
          description="先找稳定大面"
          help="关闭后严格保留模型当前朝向，适合已经人工确认过摆放的工程。"
        />
      </div>

      <div className="setting-group">
        <span className="setting-group__label">输出位置</span>
        <div className="path-row">
          <button className="path-field" type="button" onClick={onOpenOutput}>
            <FolderIcon />
            <span>{outputDir}</span>
            <ChevronIcon />
          </button>
          <Button type="button" onClick={onChooseOutput}>更改</Button>
        </div>
      </div>

      <div className="action-dock">
        <p className="action-hint">{actionHint}</p>
        <Button
          variant={busy ? "secondary" : "primary"}
          fullWidth
          disabled={!busy && !hasModels}
          onClick={busy ? onCancel : onGenerate}
        >
          {actionLabel}
        </Button>
      </div>
    </aside>
  );
}
