import Switch from "./ui/Switch";
import { ChevronIcon } from "./ui/icons";

export default function MagicToolbox({
  hideSeam,
  topIroning,
  disabled = false,
  onChange,
}: {
  hideSeam: boolean;
  topIroning: boolean;
  disabled?: boolean;
  onChange: (key: "hideSeam" | "topIroning", value: boolean) => void;
}) {
  const activeCount = Number(hideSeam) + Number(topIroning);

  return (
    <details className="magic-toolbox">
      <summary aria-label={`妙妙工具箱，${activeCount} 项已启用`}>
        <img src="./toolbox.png" alt="" />
        <span className="magic-toolbox__copy">
          <strong>妙妙工具箱</strong>
          <small>隐藏 Z 缝、顶面熨烫</small>
        </span>
        {activeCount ? (
          <span className="magic-toolbox__count">{activeCount} 项启用</span>
        ) : (
          <span className="magic-toolbox__count is-empty">未启用</span>
        )}
        <ChevronIcon />
      </summary>

      <div className="magic-toolbox__options">
        <p>勾选后自动用于下一次切片，可以同时启用。</p>
        <Switch
          checked={hideSeam}
          onChange={(checked) => onChange("hideSeam", checked)}
          label="隐藏 Z 缝"
          description="按外壁长度自动斜拼"
          help="适合手办、摆件、圆柱或大面积曲面；极短外墙和细小孔洞仍要检查切片预览。"
          disabled={disabled}
        />
        <span className="setting-divider" />
        <Switch
          checked={topIroning}
          onChange={(checked) => onChange("topIroning", checked)}
          label="顶面熨烫"
          description="顶层再走一遍，表面更平但更慢"
          help="适合顶面可见的底座、盒子和平面摆件；PETG、TPU 等易粘材料先做小样。"
          disabled={disabled}
        />
        {activeCount ? (
          <button
            className="text-button magic-toolbox__reset"
            type="button"
            disabled={disabled}
            onClick={() => {
              onChange("hideSeam", false);
              onChange("topIroning", false);
            }}
          >
            恢复默认
          </button>
        ) : null}
      </div>
    </details>
  );
}
