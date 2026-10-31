interface NumberFieldProps {
  label: string;
  value: string;
  suffix: string;
  min: number;
  max: number;
  step: number;
  highlighted?: boolean;
  onChange: (value: string) => void;
}

export default function NumberField({
  label,
  value,
  suffix,
  min,
  max,
  step,
  highlighted = false,
  onChange,
}: NumberFieldProps) {
  return (
    <label className={`number-field${highlighted ? " is-synced" : ""}`}>
      <span className="number-field__label">{label}</span>
      <span className="number-field__control">
        <input
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <span>{suffix}</span>
      </span>
    </label>
  );
}
