"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { StrategyParamField } from "@/types/trading";

interface Props {
  params: StrategyParamField[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export function StrategyParamsForm({ params, values, onChange }: Props) {
  if (params.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        This strategy has no configurable parameters.
      </p>
    );
  }

  function set(name: string, value: unknown) {
    onChange({ ...values, [name]: value });
  }

  function getVal<T>(name: string, def: T): T {
    return name in values ? (values[name] as T) : def;
  }

  return (
    <div className="space-y-4">
      {params.map((param) => {
        const id = `param-${param.name}`;

        if (param.type === "bool") {
          return (
            <div
              key={param.name}
              className="flex items-center justify-between rounded-lg border p-3"
            >
              <div className="space-y-0.5">
                <Label
                  htmlFor={id}
                  className="text-sm font-medium cursor-pointer"
                >
                  {param.label}
                </Label>
                {param.description && (
                  <p className="text-xs text-muted-foreground">
                    {param.description}
                  </p>
                )}
              </div>
              <Switch
                id={id}
                checked={getVal<boolean>(param.name, param.default as boolean)}
                onCheckedChange={(v) => set(param.name, v)}
              />
            </div>
          );
        }

        if (param.type === "select" && param.options) {
          return (
            <div key={param.name} className="space-y-1.5">
              <Label htmlFor={id}>{param.label}</Label>
              {param.description && (
                <p className="text-xs text-muted-foreground">
                  {param.description}
                </p>
              )}
              <Select
                value={String(getVal(param.name, param.default))}
                onValueChange={(v) => set(param.name, v)}
              >
                <SelectTrigger id={id}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {param.options.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }

        // int / float / str
        const isNumeric = param.type === "int" || param.type === "float";

        // For float fields we keep the raw string in state so intermediate
        // values like "0.0" or "0.00" are not collapsed to "0" by parseFloat.
        const rawValue = param.type === "float"
          ? String(getVal<string | number>(param.name, param.default as string | number))
          : String(getVal(param.name, param.default));

        return (
          <div key={param.name} className="space-y-1.5">
            <Label htmlFor={id}>{param.label}</Label>
            {param.description && (
              <p className="text-xs text-muted-foreground">
                {param.description}
              </p>
            )}
            <Input
              id={id}
              // Use "text" + inputMode for floats so the browser/parseFloat
              // cannot mangle intermediate input like "0.0" → "0".
              type={param.type === "float" ? "text" : isNumeric ? "number" : "text"}
              inputMode={param.type === "float" ? "decimal" : undefined}
              value={rawValue}
              min={param.min}
              max={param.max}
              onChange={(e) => {
                if (param.type === "int") {
                  const parsed = parseInt(e.target.value, 10);
                  set(param.name, isNaN(parsed) ? e.target.value : parsed);
                } else if (param.type === "float") {
                  // Always store the raw string so "0.0", "0.00", "-0." etc.
                  // are preserved while the user is still typing.
                  const raw = e.target.value;
                  const parsed = parseFloat(raw);
                  // If the string is a complete, unambiguous number (doesn't
                  // end with "." or trailing zeros after decimal), commit the
                  // numeric value; otherwise keep the raw string.
                  const isComplete = raw !== "" && !raw.endsWith(".") && !(/\.\d*0$/.test(raw)) && !isNaN(parsed);
                  set(param.name, isComplete ? parsed : raw);
                } else {
                  set(param.name, e.target.value);
                }
              }}
            />
          </div>
        );
      })}
    </div>
  );
}
