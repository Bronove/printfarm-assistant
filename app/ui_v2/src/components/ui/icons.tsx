import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const common = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function LayersIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z" />
      <path d="m4 12 8 4.5 8-4.5" />
      <path d="m4 16.5 8 4.5 8-4.5" />
    </svg>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M12 16V4" />
      <path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
      <path d="M5 14v5h14v-5" />
    </svg>
  );
}

export function SlidersIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M4 6h10" />
      <path d="M18 6h2" />
      <circle cx="16" cy="6" r="2" />
      <path d="M4 12h2" />
      <path d="M10 12h10" />
      <circle cx="8" cy="12" r="2" />
      <path d="M4 18h9" />
      <path d="M17 18h3" />
      <circle cx="15" cy="18" r="2" />
    </svg>
  );
}

export function FileTextIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M6 3.5h8l4 4V20H6V3.5Z" />
      <path d="M14 3.5V8h4" />
      <path d="M9 12h6" />
      <path d="M9 15.5h6" />
    </svg>
  );
}

export function MessageIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M5 5h14v11H9l-4 3V5Z" />
      <path d="M8.5 9.5h7" />
      <path d="M8.5 12.5h4.5" />
    </svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="m7 7 10 10" />
      <path d="m17 7-10 10" />
    </svg>
  );
}

export function ChevronIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="m8 10 4 4 4-4" />
    </svg>
  );
}

export function FolderIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M3.5 6.5h6l2 2h9v9.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V6.5Z" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="m5 12.5 4.2 4L19 7" />
    </svg>
  );
}

export function SparkIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M12 3.5 13.7 9l5.3 1.8-5.3 1.8L12 18l-1.7-5.4L5 10.8 10.3 9 12 3.5Z" />
      <path d="m18.5 16 .7 2.1 2.3.7-2.3.8-.7 2.1-.7-2.1-2.3-.8 2.3-.7.7-2.1Z" />
    </svg>
  );
}

export function PrinterIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <path d="M7 8V4h10v4" />
      <rect x="4" y="8" width="16" height="8" rx="2" />
      <path d="M7 16h10v4H7z" />
      <path d="M16.5 11h.01" />
    </svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <svg {...common} {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 10.8v5.2" />
      <path d="M12 7.7h.01" />
    </svg>
  );
}
