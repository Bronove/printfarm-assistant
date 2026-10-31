import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  leadingIcon?: ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
}

export default function Button({
  variant = "secondary",
  leadingIcon,
  loading = false,
  fullWidth = false,
  disabled,
  children,
  className = "",
  ...props
}: ButtonProps) {
  const classes = [
    "button",
    `button--${variant}`,
    fullWidth ? "button--full" : "",
    loading ? "is-loading" : "",
    className,
  ].filter(Boolean).join(" ");

  return (
    <button
      {...props}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      <span className="button__content" aria-hidden={loading || undefined}>
        {leadingIcon ? <span className="button__icon">{leadingIcon}</span> : null}
        <span>{children}</span>
      </span>
      {loading ? <span className="button__spinner" aria-hidden="true" /> : null}
    </button>
  );
}
