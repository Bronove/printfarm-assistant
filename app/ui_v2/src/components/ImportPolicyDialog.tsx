import { useEffect, useMemo, useRef, useState } from "react";
import type { BridgeImportedFile } from "../bridge";
import type {
  FileParameterSummary,
  ImportParameterPolicy,
  OverridableParameter,
  ParameterSourceMode,
  SliceSettings,
} from "../types";
import Button from "./ui/Button";
import { CheckIcon, CloseIcon, LayersIcon } from "./ui/icons";

const EMPTY_OVERRIDES: Record<OverridableParameter, boolean> = {
  layerHeight: false,
  infill: false,
  pattern: false,
  support: false,
};

const PATTERN_LABELS: Record<string, string> = {
  grid: "网格",
  lines: "直线",
  line: "直线",
  gyroid: "螺旋",
  honeycomb: "蜂窝",
  cubic: "立方体",
  "3dhoneycomb": "3D 蜂窝",
  concentric: "同心",
  triangles: "三角形",
};

function displayPattern(value?: string) {
  if (!value) return "未声明";
  return PATTERN_LABELS[value.toLowerCase()] ?? value;
}

function displaySupport(file: FileParameterSummary) {
  if (!file.supportEnabled) return "关闭";
  const type = file.supportType?.startsWith("tree") ? "树状" : "普通";
  return file.supportPlateOnly ? `${type} · 仅打印板` : `${type} · 全模型`;
}

function displayHabitSupport(value: SliceSettings["supportMode"]) {
  return {
    tree_plate: "树状 · 仅打印板",
    tree_all: "树状 · 全模型",
    normal_plate: "普通 · 仅打印板",
    normal_all: "普通 · 全模型",
    off: "关闭",
  }[value];
}

function summariseFile(file: FileParameterSummary) {
  const parts = [
    file.layerHeight ? `层高 ${file.layerHeight} mm` : "",
    file.infill ? `填充 ${file.infill}` : "",
    file.pattern ? displayPattern(file.pattern) : "",
    `支撑 ${displaySupport(file)}`,
  ].filter(Boolean);
  return parts.join(" · ");
}

export default function ImportPolicyDialog({
  open,
  loading,
  imported,
  localNames,
  issues,
  error,
  settings,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  loading: boolean;
  imported: BridgeImportedFile[];
  localNames: string[];
  issues: string[];
  error?: string;
  settings: SliceSettings;
  onCancel: () => void;
  onConfirm: (policy: ImportParameterPolicy) => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const customRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const cancelRef = useRef(onCancel);
  const [mode, setMode] = useState<ParameterSourceMode>("file");
  const [overrides, setOverrides] = useState(EMPTY_OVERRIDES);
  cancelRef.current = onCancel;

  const embeddedFiles = imported.filter(
    (file) => file.fileSettings?.hasEmbeddedSettings,
  );
  const fileSettings = embeddedFiles[0]?.fileSettings;
  const hasFileSettings = Boolean(fileSettings);
  const displayNames = imported.length
    ? imported.map((file) => file.relativePath || file.name)
    : localNames;

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setMode(hasFileSettings ? "file" : "habit");
    setOverrides(EMPTY_OVERRIDES);
    window.requestAnimationFrame(() => dialogRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loading) {
        cancelRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [open, loading, hasFileSettings]);

  useEffect(() => {
    if (!open || mode !== "custom") return;
    window.requestAnimationFrame(() => {
      customRef.current?.scrollIntoView({ block: "start" });
    });
  }, [mode, open]);

  const customRows = useMemo(() => [
    {
      key: "layerHeight" as const,
      label: "层高",
      fileValue: fileSettings?.layerHeight
        ? `${fileSettings.layerHeight} mm`
        : "未声明",
      habitValue: `${settings.layerHeight || "0.16"} mm`,
    },
    {
      key: "infill" as const,
      label: "填充",
      fileValue: fileSettings?.infill || "未声明",
      habitValue: `${settings.infill || "15"}%`,
    },
    {
      key: "pattern" as const,
      label: "填充图案",
      fileValue: displayPattern(fileSettings?.pattern),
      habitValue: displayPattern(settings.pattern),
    },
    {
      key: "support" as const,
      label: "支撑",
      fileValue: fileSettings ? displaySupport(fileSettings) : "未声明",
      habitValue: displayHabitSupport(settings.supportMode),
    },
  ], [fileSettings, settings]);

  if (!open) return null;

  const chooseMode = (nextMode: ParameterSourceMode) => {
    setMode(nextMode);
    if (nextMode === "file") setOverrides(EMPTY_OVERRIDES);
    if (nextMode === "habit") {
      setOverrides({
        layerHeight: true,
        infill: true,
        pattern: true,
        support: true,
      });
    }
  };

  const confirm = () => {
    onConfirm({
      mode,
      overrides: mode === "habit"
        ? {
            layerHeight: true,
            infill: true,
            pattern: true,
            support: true,
          }
        : mode === "file"
          ? EMPTY_OVERRIDES
          : overrides,
    });
  };

  const modelCount = imported.length || localNames.length;
  const selectedOverrideCount = Object.values(overrides).filter(Boolean).length;

  return (
    <div className="import-policy-layer">
      <div
        className="import-policy-scrim"
        aria-hidden="true"
        onClick={() => {
          if (!loading) onCancel();
        }}
      />
      <section
        ref={dialogRef}
        className="import-policy-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-policy-title"
        aria-describedby="import-policy-description"
        tabIndex={-1}
      >
        <header className="import-policy-header">
          <span className="import-policy-header__icon" aria-hidden="true">
            <LayersIcon />
          </span>
          <div>
            <span className="import-policy-eyebrow">导入设置</span>
            <h2 id="import-policy-title">这些参数听谁的？</h2>
            <p id="import-policy-description">
              3MF 内已经带了工艺参数。本次切片可以沿用它，也可以换成你的打印习惯。
            </p>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="关闭参数选择"
            disabled={loading}
            onClick={onCancel}
          >
            <CloseIcon />
          </button>
        </header>

        <div className="import-policy-body">
          <section className="import-file-summary" aria-live="polite">
            <div className="import-file-summary__heading">
              <div>
                <strong>
                  {displayNames.length === 1
                    ? displayNames[0]
                    : `已选择 ${modelCount} 个模型`}
                </strong>
                <span>
                  {loading
                    ? "正在读取文件里的层高、填充和支撑参数…"
                    : hasFileSettings
                      ? `已读取 ${embeddedFiles.length} 个带参数的 3MF`
                      : "没有找到文件内嵌参数"}
                </span>
              </div>
              {!loading && hasFileSettings ? (
                <span className="import-file-summary__badge">
                  <CheckIcon />
                  读取成功
                </span>
              ) : null}
            </div>

            {loading ? (
              <div className="import-parameter-skeleton" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            ) : fileSettings ? (
              <>
                <div className="import-parameter-grid">
                  <div>
                    <span>文件层高</span>
                    <strong>{fileSettings.layerHeight || "未声明"}{fileSettings.layerHeight ? " mm" : ""}</strong>
                  </div>
                  <div>
                    <span>填充</span>
                    <strong>{fileSettings.infill || "未声明"}</strong>
                  </div>
                  <div>
                    <span>填充图案</span>
                    <strong>{displayPattern(fileSettings.pattern)}</strong>
                  </div>
                  <div>
                    <span>支撑</span>
                    <strong>{displaySupport(fileSettings)}</strong>
                  </div>
                </div>
                <p className="import-file-summary__caption">
                  文件参数：{summariseFile(fileSettings)}
                </p>
              </>
            ) : null}
          </section>

          {error ? (
            <div className="import-policy-error" role="alert">
              <strong>参数读取失败</strong>
              <span>{error}</span>
            </div>
          ) : null}

          {issues.length ? (
            <p className="import-policy-issue">{issues.join("；")}</p>
          ) : null}

          <fieldset className="import-policy-options" disabled={loading}>
            <legend>这次怎么处理参数</legend>

            <label className={`import-policy-option${mode === "file" ? " is-selected" : ""}${!hasFileSettings ? " is-disabled" : ""}`}>
              <input
                type="radio"
                name="import-parameter-source"
                value="file"
                checked={mode === "file"}
                disabled={!hasFileSettings}
                onChange={() => chooseMode("file")}
              />
              <span className="import-policy-radio" aria-hidden="true" />
              <span className="import-policy-option__copy">
                <span className="import-policy-option__title">
                  <strong>跟随文件</strong>
                  {hasFileSettings ? <small>推荐</small> : null}
                </span>
                <span>保留 3MF 中的层高、填充、图案和支撑，不改动原工程设置。</span>
              </span>
              <span className="import-policy-option__preview">
                {fileSettings?.layerHeight ? `${fileSettings.layerHeight} mm` : "原设置"}
              </span>
            </label>

            <label className={`import-policy-option${mode === "habit" ? " is-selected" : ""}`}>
              <input
                type="radio"
                name="import-parameter-source"
                value="habit"
                checked={mode === "habit"}
                onChange={() => chooseMode("habit")}
              />
              <span className="import-policy-radio" aria-hidden="true" />
              <span className="import-policy-option__copy">
                <span className="import-policy-option__title">
                  <strong>使用我的习惯</strong>
                </span>
                <span>改用右侧当前参数，适合你每次都用固定配方。</span>
              </span>
              <span className="import-policy-option__preview">
                {settings.layerHeight} mm
              </span>
            </label>

            <label className={`import-policy-option${mode === "custom" ? " is-selected" : ""}${!hasFileSettings ? " is-disabled" : ""}`}>
              <input
                type="radio"
                name="import-parameter-source"
                value="custom"
                checked={mode === "custom"}
                disabled={!hasFileSettings}
                onChange={() => chooseMode("custom")}
              />
              <span className="import-policy-radio" aria-hidden="true" />
              <span className="import-policy-option__copy">
                <span className="import-policy-option__title">
                  <strong>逐项选择</strong>
                </span>
                <span>只替换你勾选的参数，例如只隐藏 Z 缝，不动层高。</span>
              </span>
              <span className="import-policy-option__preview">
                {selectedOverrideCount ? `替换 ${selectedOverrideCount} 项` : "灵活组合"}
              </span>
            </label>
          </fieldset>

          {mode === "custom" && hasFileSettings ? (
            <section
              ref={customRef}
              className="import-custom-parameters"
              aria-label="逐项参数选择"
            >
              <div className="import-custom-parameters__heading">
                <strong>逐项覆盖</strong>
                <span>勾选后才使用右侧习惯值</span>
              </div>
              {customRows.map((row) => (
                <label className="import-custom-row" key={row.key}>
                  <span className="import-custom-row__name">{row.label}</span>
                  <span className="import-custom-row__source">
                    <small>文件</small>
                    <strong>{row.fileValue}</strong>
                  </span>
                  <span className="import-custom-row__arrow" aria-hidden="true">→</span>
                  <span className="import-custom-row__source">
                    <small>我的习惯</small>
                    <strong>{row.habitValue}</strong>
                  </span>
                  <input
                    type="checkbox"
                    checked={overrides[row.key]}
                    onChange={(event) => {
                      setOverrides((current) => ({
                        ...current,
                        [row.key]: event.target.checked,
                      }));
                    }}
                  />
                  <span className="import-custom-row__check" aria-hidden="true">
                    <CheckIcon />
                  </span>
                </label>
              ))}
              <p className="import-custom-parameters__note">
                “隐藏 Z 缝”和“顶面熨烫”是独立工具箱开关，不受这里影响。
              </p>
            </section>
          ) : null}
        </div>

        <footer className="import-policy-footer">
          <span>
            {loading
              ? "正在读取参数…"
              : mode === "file"
                ? "本次保留文件参数"
                : mode === "habit"
                  ? "本次使用当前打印习惯"
                  : `本次覆盖 ${selectedOverrideCount} 项参数`}
          </span>
          <div>
            <Button type="button" onClick={onCancel} disabled={loading}>
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={loading}
              disabled={Boolean(error)}
              onClick={confirm}
            >
              按此参数导入
            </Button>
          </div>
        </footer>
      </section>
    </div>
  );
}
