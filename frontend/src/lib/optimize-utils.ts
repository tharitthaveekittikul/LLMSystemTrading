export interface StrategyItem {
  id: number;
  name: string;
  execution_mode: string;
  primary_tf: string;
  context_tfs: string[];
  strategy_key: string | null;
}

export interface ParamField {
  name: string;
  label: string;
  type: "int" | "float" | "bool" | "str" | "select";
  default: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
  optimize?: boolean;
}

/** One row in the sweep builder: the user defines the values to try for a param */
export interface SweepRow {
  name: string;
  label: string;
  type: "int" | "float";
  enabled: boolean;
  mode: "range" | "list"; // range = min/max/step; list = comma-separated values
  min: string;
  max: string;
  step: string;
  list: string; // comma-separated
}

export const METRICS = [
  { value: "sharpe_ratio", label: "Sharpe Ratio" },
  { value: "profit_factor", label: "Profit Factor" },
  { value: "total_return_pct", label: "Total Return %" },
  { value: "win_rate", label: "Win Rate" },
  { value: "expectancy", label: "Expectancy" },
  { value: "max_drawdown_pct", label: "Max Drawdown % (lower = better)" },
  { value: "recovery_factor", label: "Recovery Factor" },
  { value: "sortino_ratio", label: "Sortino Ratio" },
];

/** Parse MT5 tab-separated CSV to extract start/end date strings (YYYY-MM-DD). */
export function parseMt5CsvDates(
  file: File,
): Promise<{ startDate: string; endDate: string } | null> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const dataLines = text
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l && !l.startsWith("<"));
        if (dataLines.length === 0) {
          resolve(null);
          return;
        }
        const toDate = (line: string) =>
          line.split("\t")[0]?.replace(/\./g, "-") ?? null;
        const start = toDate(dataLines[0]);
        const end = toDate(dataLines[dataLines.length - 1]);
        resolve(start && end ? { startDate: start, endDate: end } : null);
      } catch {
        resolve(null);
      }
    };
    reader.onerror = () => resolve(null);
    reader.readAsText(file);
  });
}

export function generateRange(
  min: number,
  max: number,
  step: number,
  isInt: boolean,
): number[] {
  const values: number[] = [];
  let cur = min;
  while (cur <= max + 1e-9) {
    values.push(isInt ? Math.round(cur) : parseFloat(cur.toFixed(6)));
    cur += step;
    if (values.length > 50) break; // safety cap
  }
  return [...new Set(values)];
}

export function parseList(raw: string, isInt: boolean): number[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => (isInt ? parseInt(s, 10) : parseFloat(s)))
    .filter((v) => !isNaN(v));
}
