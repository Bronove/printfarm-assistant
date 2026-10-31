import type { ReactNode } from "react";
import { CheckIcon } from "./icons";

type Tone = "info" | "success" | "warning" | "error";

export default function StatusBanner({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`status-banner status-banner--${tone}`} role="status">
      <span className="status-banner__icon" aria-hidden="true">
        <CheckIcon />
      </span>
      <span className="status-banner__copy">
        {title ? <strong>{title}</strong> : null}
        <span>{children}</span>
      </span>
      {action ? <span className="status-banner__action">{action}</span> : null}
    </div>
  );
}
