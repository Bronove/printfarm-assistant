import { useEffect, useRef, useState } from "react";
import { InfoIcon } from "./icons";

export default function HelpTip({
  label,
  children,
  inline = false,
}: {
  label: string;
  children: string;
  inline?: boolean;
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const closeTimer = useRef<number | null>(null);
  const [visible, setVisible] = useState(false);

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const show = () => {
    cancelClose();
    if (detailsRef.current && !detailsRef.current.open) {
      detailsRef.current.open = true;
    }
    window.requestAnimationFrame(() => setVisible(true));
  };

  const hide = () => {
    cancelClose();
    setVisible(false);
    closeTimer.current = window.setTimeout(() => {
      if (detailsRef.current) detailsRef.current.open = false;
      closeTimer.current = null;
    }, 160);
  };

  useEffect(() => cancelClose, []);

  return (
    <details
      ref={detailsRef}
      className={[
        "help-tip",
        inline ? "help-tip--inline" : "",
        visible ? "is-visible" : "",
      ].filter(Boolean).join(" ")}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <summary
        aria-label={label}
        aria-expanded={visible}
        onClick={(event) => {
          event.preventDefault();
          show();
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") hide();
        }}
      >
        <InfoIcon />
      </summary>
      <p>{children}</p>
    </details>
  );
}
