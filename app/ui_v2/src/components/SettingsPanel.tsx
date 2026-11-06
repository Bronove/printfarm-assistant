import Button from "./ui/Button";
import MagicToolbox from "./MagicToolbox";
import NumberField from "./ui/NumberField";
import Switch from "./ui/Switch";
import { CheckIcon, ChevronIcon, FolderIcon, PrinterIcon } from "./ui/icons";
import useSmoothWheel from "../hooks/useSmoothWheel";
import type {
  InfillPattern,
  MulticolorStrategy,
  SliceSettings,
  SupportMode,
  WorkspaceMode,
} from "../types";

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
      ? settings.batchOutputMode === "combined"
        ? "生成可编辑 3MF"
        : "开始批量切片"
      : mode === "multicolor"
        ? "开始多色排盘"
      : mode === "figurine"
        ? "生成手办切片"
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
  const canOptimizeGeometry = (
    settings.outputMode === "gcode" && mode !== "figurine"
  );
  const policyOverrideCount = settings.parameterPolicy
    ? Object.values(settings.parameterPolicy.overrides).filter(Boolean).length
    : 0;

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
              disabled={busy}
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
        <strong>
          {mode === "workbench"
            ? "简单文件流程"
            : mode === "multicolor"
              ? "多色分类摆盘"
              : mode === "figurine"
                ? "手办稳定朝向"
              : settings.batchOutputMode === "combined"
                ? "多文件合并排盘"
                : "批量统一参数"}
        </strong>
        <span>
          {mode === "workbench"
            ? "不拆件、不主动重排，直接按当前朝向切片。"
            : mode === "multicolor"
              ? "先按颜色和策略生成布局，再由助手调用 Bambu 开启支撑试切检修。"
              : mode === "figurine"
                ? "优先保留原姿态，复杂支撑方向会单独提示。"
              : settings.batchOutputMode === "combined"
                ? "按数量展开文件，生成一个可在 Bambu Studio 继续编辑的多盘工程。"
                : "所有文件沿用右侧同一套参数连续切片。"}
        </span>
      </div>

      {mode === "batch" ? (
        <div className="setting-group">
          <span className="setting-group__label">批量输出</span>
          <label className="parameter-select">
            <span>输出方式</span>
            <select
              aria-label="批量输出方式"
              value={settings.batchOutputMode ?? "separate"}
              disabled={busy}
              onChange={(event) => onChange(
                "batchOutputMode",
                event.target.value as "separate" | "combined",
              )}
            >
              <option value="separate">分别切片</option>
              <option value="combined">合并排盘</option>
            </select>
          </label>
          {settings.batchOutputMode === "combined" ? (
            <Switch
              checked={Boolean(settings.supportOverlap)}
              onChange={(checked) => onChange("supportOverlap", checked)}
              label="允许支撑重叠"
              description="更快；冲突时失败盘自动改安全模式"
              disabled={busy}
            />
          ) : null}
        </div>
      ) : null}

      {mode === "multicolor" ? (
        <div className="setting-group">
          <span className="setting-group__label">多色摆盘</span>
          <label className="parameter-select">
            <span>策略</span>
            <select
              aria-label="多色摆盘策略"
              value={settings.multicolorStrategy}
              disabled={busy}
              onChange={(event) => onChange(
                "multicolorStrategy",
                event.target.value as MulticolorStrategy,
              )}
            >
              <option value="zero_flush">零串色</option>
              <option value="fewer_plates">满盘参考</option>
              <option value="time_budget">按盘时长</option>
            </select>
          </label>
          <label className="parameter-select">
            <span>单盘最多颜色</span>
            <select
              aria-label="单盘最多颜色"
              value={settings.maxColors}
              disabled={busy}
              onChange={(event) => onChange("maxColors", event.target.value)}
            >
              <option value="1">1 色</option>
              <option value="2">2 色</option>
              <option value="4">4 色</option>
            </select>
          </label>
          {settings.multicolorStrategy === "time_budget" ? (
            <NumberField
              label="每盘目标"
              value={settings.targetHours}
              suffix="小时"
              min={1}
              max={12}
              step={1}
              disabled={busy}
              onChange={(value) => onChange("targetHours", value)}
            />
          ) : null}
        </div>
      ) : null}

      {settings.parameterPolicy ? (
        <div className="parameter-source-note">
          <span className="parameter-source-note__icon" aria-hidden="true">
            <CheckIcon />
          </span>
          <span>
            <strong>
              参数来源：
              {settings.parameterPolicy.mode === "file"
                ? "跟随文件"
                : settings.parameterPolicy.mode === "habit"
                  ? "我的习惯"
                  : `逐项覆盖 ${policyOverrideCount} 项`}
            </strong>
            <small>
              {settings.parameterPolicy.mode === "habit"
                ? "本次所有模型使用右侧参数"
                : "未覆盖的工艺参数继续沿用 3MF"}
            </small>
          </span>
        </div>
      ) : null}

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
            disabled={busy}
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
            disabled={busy}
            onChange={(value) => onChange("infill", value)}
          />
        </div>
        <label className={`parameter-select${recentKeys.includes("pattern") ? " is-synced" : ""}`}>
          <span>填充图案</span>
          <select
            value={settings.pattern}
            disabled={busy}
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
            disabled={busy}
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
        disabled={busy}
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
              disabled={busy}
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
              disabled={busy}
              onChange={(event) => onChange("bedType", event.target.value)}
            >
              <option value="Textured PEI Plate">纹理钢板</option>
              <option value="Cool Plate">冷却板</option>
              <option value="High Temp Plate">高温板</option>
              <option value="Engineering Plate">工程板</option>
            </select>
          </label>
          {mode === "batch" && settings.batchOutputMode === "combined" ? (
            <div className="parameter-select">
              <span>输出</span>
              <span className="parameter-select__value">可编辑多盘 3MF</span>
            </div>
          ) : (
            <label className={`parameter-select${recentKeys.includes("outputMode") ? " is-synced" : ""}`}>
              <span>输出</span>
              <select
                aria-label="输出类型"
                value={settings.outputMode}
                disabled={busy}
                onChange={(event) => onChange("outputMode", event.target.value as "gcode" | "3mf")}
              >
                <option value="gcode">可直接打印 G-code 3MF</option>
                <option value="3mf">仅生成可编辑 3MF</option>
              </select>
            </label>
          )}
          <NumberField
            label="克隆数量"
            value={settings.clone}
            suffix="个"
            min={1}
            max={100}
            step={1}
            highlighted={recentKeys.includes("clone")}
            disabled={busy}
            onChange={(value) => onChange("clone", value)}
          />
          <Switch
            checked={settings.tightPacking}
            onChange={(checked) => onChange("tightPacking", checked)}
            label="最省空间"
            description={canOptimizeGeometry
              ? "紧凑摆盘，优先减少盘数"
              : "需切换为可直接打印 G-code"}
            disabled={!canOptimizeGeometry || busy}
          />
          <Switch
            checked={settings.minSupport}
            onChange={(checked) => onChange("minSupport", checked)}
            label="最少支撑"
            description={canOptimizeGeometry
              ? "多比较方向，耗时更长"
              : "需切换为可直接打印 G-code"}
            disabled={!canOptimizeGeometry || busy}
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
          disabled={busy}
        />
        <span className="setting-divider" />
        <Switch
          checked={settings.orientation}
          onChange={(checked) => onChange("orientation", checked)}
          label="自动定向"
          description="先找稳定大面"
          help="关闭后严格保留模型当前朝向，适合已经人工确认过摆放的工程。"
          disabled={busy}
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
          <Button type="button" disabled={busy} onClick={onChooseOutput}>更改</Button>
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
