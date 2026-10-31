import { useEffect, useRef, useState } from "react";
import {
  getLocalLogs,
  getMetadata,
  openLogDirectory,
  updateRule,
  type BridgeMeta,
} from "../bridge";
import { CloseIcon } from "./ui/icons";

const PARAMETER_NAMES: Record<string, string> = {
  layer_height: "层高",
  infill: "填充",
  pattern: "填充图案",
  support: "支撑方式",
  clone: "克隆数量",
  tight: "最省空间",
  min_support: "最少支撑",
  orient: "自动定向",
  arrange: "自动排列",
  filament: "耗材",
  _mat_family: "材料类别",
};

function displayValue(value: unknown) {
  if (value === true) return "开启";
  if (value === false) return "关闭";
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function SettingsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [meta, setMeta] = useState<BridgeMeta | null>(null);
  const [metaLoading, setMetaLoading] = useState(true);
  const [error, setError] = useState("");
  const [logText, setLogText] = useState("");
  const [logPath, setLogPath] = useState("");
  const [logLoading, setLogLoading] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const loadMeta = () => {
    setMetaLoading(true);
    setError("");
    void getMetadata()
      .then(setMeta)
      .catch((reason) => setError(
        reason instanceof Error ? reason.message : String(reason),
      ))
      .finally(() => setMetaLoading(false));
  };

  const loadLogs = () => {
    setLogLoading(true);
    setError("");
    void getLocalLogs()
      .then((result) => {
        setLogText(result.text);
        setLogPath(result.path);
      })
      .catch((reason) => setError(
        reason instanceof Error ? reason.message : String(reason),
      ))
      .finally(() => setLogLoading(false));
  };

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setError("");
    loadMeta();
    loadLogs();
    window.requestAnimationFrame(() => dialogRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const applyRule = async (
    action: "toggle" | "remove" | "clear" | "remove-default",
    norm = "",
    enabled = true,
  ) => {
    try {
      setMeta(await updateRule(action, norm, enabled));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="settings-layer">
      <div className="settings-scrim" aria-hidden="true" onClick={onClose} />
      <section
        ref={dialogRef}
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-dialog-title"
        tabIndex={-1}
      >
        <header className="settings-dialog__header">
          <div>
            <h2 id="settings-dialog-title">设置</h2>
            <p>打印习惯、使用统计和运行日志都保存在这台电脑。</p>
          </div>
          <button className="icon-button" type="button" aria-label="关闭设置" onClick={onClose}>
            <CloseIcon />
          </button>
        </header>

        {error ? <p className="settings-dialog__error">{error}</p> : null}
        {metaLoading && !meta ? <p className="settings-dialog__loading">正在读取本地设置…</p> : null}
        <div className="settings-dialog__body">
          {meta ? (
            <section>
              <h3>打印习惯</h3>
              <p>{meta.learning.summary}</p>

              {Object.keys(meta.learning.defaults).length ? (
                <>
                  <h4 className="settings-subheading">习惯默认</h4>
                  <div className="rule-list">
                    {Object.entries(meta.learning.defaults).map(([key, value]) => (
                      <div className="rule-row" key={key}>
                        <span>{PARAMETER_NAMES[key] || key} = {displayValue(value)}</span>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => void applyRule("remove-default", key)}
                        >
                          删除
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}

              {meta.learning.phraseRules.length ? (
                <>
                  <h4 className="settings-subheading">记住的说法</h4>
                  <div className="rule-list">
                    {meta.learning.phraseRules.map((rule) => (
                      <div className="rule-row" key={rule.norm}>
                        <label>
                          <input
                            type="checkbox"
                            checked={rule.enabled !== false}
                            onChange={(event) => {
                              void applyRule("toggle", rule.norm, event.target.checked);
                            }}
                          />
                          <span>{rule.norm}</span>
                        </label>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => void applyRule("remove", rule.norm)}
                        >
                          删除
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p>还没有形成打印习惯。正常切片几次后，助手会自动记住常用说法和参数。</p>
              )}

              {Object.keys(meta.learning.defaults).length || meta.learning.phraseRules.length ? (
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void applyRule("clear")}
                >
                  清除全部打印习惯
                </button>
              ) : null}
            </section>
          ) : null}

          {meta ? (
            <section>
              <h3>使用数据</h3>
              <p>本机共记录 {meta.usage.total} 条使用事件，不会自动上传。</p>
              {meta.usage.events.length ? (
                <div className="usage-counts">
                  {meta.usage.events.map(([name, count]) => (
                    <span key={name}>{name} {count}</span>
                  ))}
                </div>
              ) : <p>还没有使用记录。</p>}
            </section>
          ) : null}

          <section>
            <h3>本地日志</h3>
            <p>操作、OCR、参数、切片输出和错误只写入本机日志文件。</p>
            {logPath ? <p className="settings-log-path">{logPath}</p> : null}
            <div className="log-actions">
              <button
                type="button"
                className="text-button"
                disabled={logLoading}
                onClick={loadLogs}
              >
                {logLoading ? "正在读取…" : "刷新最近日志"}
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  void openLogDirectory().catch((reason) => setError(
                    reason instanceof Error ? reason.message : String(reason),
                  ));
                }}
              >
                打开日志目录
              </button>
            </div>
            {logText ? (
              <pre className="settings-log">{logText}</pre>
            ) : (
              !logLoading && !error ? <p>暂无可显示的日志。</p> : null
            )}
          </section>
        </div>
      </section>
    </div>
  );
}
