import HelpTip from "./HelpTip";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  help?: string;
  disabled?: boolean;
}

export default function Switch({
  checked,
  onChange,
  label,
  description,
  help,
  disabled = false,
}: SwitchProps) {
  return (
    <div className={`switch-row${disabled ? " is-disabled" : ""}`}>
      <span className="switch-row__copy">
        <span className="switch-row__label-line">
          <span className="switch-row__label">{label}</span>
          {help ? <HelpTip label={`${label}说明`} inline>{help}</HelpTip> : null}
        </span>
        {description ? <span className="switch-row__description">{description}</span> : null}
      </span>
      <button
        type="button"
        className="switch"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span className="switch__thumb" />
      </button>
    </div>
  );
}
