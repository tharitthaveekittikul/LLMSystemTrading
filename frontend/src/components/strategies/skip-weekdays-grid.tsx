"use client";

// 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun  (Python weekday() convention)
const DAYS: { label: string; short: string; value: number }[] = [
  { label: "Monday",    short: "Mon", value: 0 },
  { label: "Tuesday",   short: "Tue", value: 1 },
  { label: "Wednesday", short: "Wed", value: 2 },
  { label: "Thursday",  short: "Thu", value: 3 },
  { label: "Friday",    short: "Fri", value: 4 },
  { label: "Saturday",  short: "Sat", value: 5 },
  { label: "Sunday",    short: "Sun", value: 6 },
];

const PRESETS: { label: string; days: number[] }[] = [
  { label: "None",     days: [] },
  { label: "Weekends", days: [5, 6] },
  { label: "Mon+Fri",  days: [0, 4] },
];

interface Props {
  days: number[];
  onChange: (days: number[]) => void;
}

export function SkipWeekdaysGrid({ days, onChange }: Props) {
  function toggle(d: number) {
    const next = days.includes(d)
      ? days.filter((x) => x !== d)
      : [...days, d].sort((a, b) => a - b);
    onChange(next);
  }

  const skipCount = days.length;
  const runCount = 7 - skipCount;

  return (
    <div className="space-y-3">
      {/* Presets */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground shrink-0">Quick:</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onChange([...p.days])}
            className="text-xs rounded border px-2 py-0.5 transition-colors hover:bg-muted"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-1">
        {DAYS.map(({ label, short, value }) => {
          const skipped = days.includes(value);
          return (
            <button
              key={value}
              type="button"
              onClick={() => toggle(value)}
              title={skipped ? `${label} — skip` : `${label} — run`}
              className={`
                rounded text-xs font-medium py-1.5 transition-colors select-none
                ${
                  skipped
                    ? "bg-destructive/15 text-destructive border border-destructive/40 hover:bg-destructive/25"
                    : "bg-muted/50 text-muted-foreground border border-transparent hover:bg-muted"
                }
              `}
            >
              {short}
            </button>
          );
        })}
      </div>

      {/* Summary */}
      <p className="text-xs text-muted-foreground">
        <span className="text-destructive font-medium">✕ Skip {skipCount} day{skipCount !== 1 ? "s" : ""}</span>
        {"  ·  "}
        <span className="font-medium">▷ Run {runCount} day{runCount !== 1 ? "s" : ""}</span>
      </p>
    </div>
  );
}
