interface ScoreRingProps {
  value: number;
  size?: number;
  strokeWidth?: number;
  label?: string;
  colorClass?: string;
}

function toneForValue(value: number): string {
  if (value >= 70) return "text-success";
  if (value >= 50) return "text-warning";
  return "text-danger";
}

export function ScoreRing({ value, size = 120, strokeWidth = 10, label, colorClass }: ScoreRingProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const tone = colorClass ?? toneForValue(clamped);

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} strokeWidth={strokeWidth} className="stroke-canvas" fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          fill="none"
          className={`${tone} transition-[stroke-dashoffset] duration-500 ease-out`}
          stroke="currentColor"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-ink-900">{Math.round(clamped)}%</span>
        {label && <span className="text-[11px] text-ink-300">{label}</span>}
      </div>
    </div>
  );
}
