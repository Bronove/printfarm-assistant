import type { ReactNode } from "react";
import { CheckIcon, InfoIcon } from "./icons";

type Tone = "info" | "success" | "warning" | "error";

export default function StatusBanner({
  tone = "info",
  title,
  children,
  action,
  loading = false,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
  loading?: boolean;
}) {
  const StatusIcon = tone === "success" ? CheckIcon : InfoIcon;

  return (
    <div className={`status-banner status-banner--${tone}`} role="status">
      <span className="status-banner__icon" aria-hidden="true">
        <StatusIcon />
      </span>
      <span className="status-banner__copy">
        {title ? <strong>{title}</strong> : null}
        <span>{children}</span>
        {loading ? (
          <span
            className="status-banner__spinner"
            role="status"
            aria-label="正在处理"
          />
        ) : null}
      </span>
      {action ? <span className="status-banner__action">{action}</span> : null}
    </div>
  );
}
