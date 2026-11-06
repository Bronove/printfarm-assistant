import type { ModeDefinition, WorkspaceMode } from "../types";
import { SlidersIcon } from "./ui/icons";

const APP_VERSION =
  import.meta.env.VITE_APP_VERSION?.trim() || "2.1.0-dev.9";

export default function AppHeader({
  modes,
  activeMode,
  onModeChange,
  onSettingsOpen,
}: {
  modes: ModeDefinition[];
  activeMode: WorkspaceMode;
  onModeChange: (mode: WorkspaceMode) => void;
  onSettingsOpen: () => void;
}) {
  return (
    <header className="app-header">
      <a className="brand" href="#" aria-label="打印农场助手首页">
        <img
          className="brand__icon"
          src="./icon.ico"
          alt="打印农场助手图标"
          data-testid="app-brand-icon"
        />
        <span className="brand__copy">
          <strong>打印农场助手</strong>
          <span>PrintFarm Assistant · v{APP_VERSION}</span>
        </span>
      </a>

      <nav className="mode-tabs" aria-label="工作模式">
        {modes.map((mode) => (
          <button
            type="button"
            key={mode.id}
            className={`mode-tab${activeMode === mode.id ? " is-active" : ""}`}
            aria-current={activeMode === mode.id ? "page" : undefined}
            onClick={() => onModeChange(mode.id)}
          >
            {mode.label}
          </button>
        ))}
      </nav>

      <div className="header-actions">
        <button
          className="icon-button"
          type="button"
          aria-label="设置"
          title="打印习惯、使用数据和本地日志"
          onClick={onSettingsOpen}
        >
          <SlidersIcon />
        </button>
      </div>
    </header>
  );
}
