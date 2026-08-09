import { ReactElement, ReactNode } from "react";

export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}): ReactElement {
  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <h3>{title}</h3>
        {description && <p>{description}</p>}
      </div>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

export function Row({
  label,
  hint,
  htmlFor,
  children,
  stacked = false,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
  stacked?: boolean;
}): ReactElement {
  return (
    <div className={`setting-row ${stacked ? "stacked" : ""}`}>
      <div className="setting-row-text">
        <label htmlFor={htmlFor}>{label}</label>
        {hint && <p>{hint}</p>}
      </div>
      <div className="setting-row-control">{children}</div>
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  id,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
  id?: string;
}): ReactElement {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className="toggle"
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-thumb" />
    </button>
  );
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}): ReactElement {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          className={value === option.value ? "selected" : ""}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
