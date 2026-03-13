"use client";

interface Props {
  hours: number[];
  timezone: string;
  onChange: (hours: number[], timezone: string) => void;
}

const TIMEZONES = [
  { label: "GMT+7 — Asia/Bangkok", value: "Asia/Bangkok" },
  { label: "GMT+0 — UTC", value: "UTC" },
  { label: "GMT+0/+1 — Europe/London", value: "Europe/London" },
  { label: "GMT-5/-4 — America/New_York", value: "America/New_York" },
  { label: "GMT+9 — Asia/Tokyo", value: "Asia/Tokyo" },
  { label: "GMT+8 — Asia/Singapore", value: "Asia/Singapore" },
  { label: "GMT+10/+11 — Australia/Sydney", value: "Australia/Sydney" },
];

// Preset patterns (hours to skip, in local timezone)
const PRESETS: { label: string; hours: number[] }[] = [
  { label: "None", hours: [] },
  { label: "Low Liquidity (GMT+7)", hours: [0, 1, 2, 3, 10, 11, 12, 13] },
  { label: "Asia Close (GMT+7)", hours: [7, 8, 9, 10, 11] },
];

export function SkipHoursGrid({ hours, timezone, onChange }: Props) {
  function toggle(h: number) {
    const next = hours.includes(h)
      ? hours.filter((x) => x !== h)
      : [...hours, h].sort((a, b) => a - b);
    onChange(next, timezone);
  }

  function applyPreset(preset: number[]) {
    onChange([...preset], timezone);
  }

  const skipCount = hours.length;
  const runCount = 24 - skipCount;

  return (
    <div className="space-y-3">
      {/* Timezone selector */}
      <div className="flex items-center gap-2">
        <label className="text-xs font-medium text-muted-foreground w-20 shrink-0">
          Timezone
        </label>
        <select
          value={timezone}
          onChange={(e) => onChange(hours, e.target.value)}
          className="flex-1 text-sm rounded-md border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>
              {tz.label}
            </option>
          ))}
        </select>
      </div>

      {/* Presets */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground shrink-0">Quick:</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => applyPreset(p.hours)}
            className="text-xs rounded border px-2 py-0.5 transition-colors hover:bg-muted"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Hour grid — row 1: 00–11 */}
      <div className="space-y-1.5">
        <div className="grid grid-cols-12 gap-1">
          {Array.from({ length: 12 }, (_, i) => i).map((h) => (
            <HourCell key={h} hour={h} skipped={hours.includes(h)} onToggle={toggle} />
          ))}
        </div>
        {/* row 2: 12–23 */}
        <div className="grid grid-cols-12 gap-1">
          {Array.from({ length: 12 }, (_, i) => i + 12).map((h) => (
            <HourCell key={h} hour={h} skipped={hours.includes(h)} onToggle={toggle} />
          ))}
        </div>
      </div>

      {/* Summary */}
      <p className="text-xs text-muted-foreground">
        <span className="text-destructive font-medium">✕ Skip {skipCount} h</span>
        {"  ·  "}
        <span className="font-medium">▷ Run {runCount} h</span>
      </p>
    </div>
  );
}

function HourCell({
  hour,
  skipped,
  onToggle,
}: {
  hour: number;
  skipped: boolean;
  onToggle: (h: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onToggle(hour)}
      title={skipped ? `${String(hour).padStart(2, "0")}:00 — skip` : `${String(hour).padStart(2, "0")}:00 — run`}
      className={`
        rounded text-xs font-mono py-1 transition-colors select-none
        ${
          skipped
            ? "bg-destructive/15 text-destructive border border-destructive/40 hover:bg-destructive/25"
            : "bg-muted/50 text-muted-foreground border border-transparent hover:bg-muted"
        }
      `}
    >
      {String(hour).padStart(2, "0")}
    </button>
  );
}
