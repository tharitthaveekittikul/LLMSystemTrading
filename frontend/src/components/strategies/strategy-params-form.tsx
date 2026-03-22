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
            <div key={param.name} className="flex items-center justify-between rounded-lg border p-3">
              <div className="space-y-0.5">
                <Label htmlFor={id} className="text-sm font-medium cursor-pointer">
                  {param.label}
                </Label>
                {param.description && (
                  <p className="text-xs text-muted-foreground">{param.description}</p>
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
                <p className="text-xs text-muted-foreground">{param.description}</p>
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
        return (
          <div key={param.name} className="space-y-1.5">
            <Label htmlFor={id}>{param.label}</Label>
            {param.description && (
              <p className="text-xs text-muted-foreground">{param.description}</p>
            )}
            <Input
              id={id}
              type={isNumeric ? "number" : "text"}
              value={String(getVal(param.name, param.default))}
              min={param.min}
              max={param.max}
              step={
                param.step ??
                (param.type === "int" ? 1 : param.type === "float" ? 0.001 : undefined)
              }
              onChange={(e) => {
                if (param.type === "int") {
                  set(param.name, parseInt(e.target.value, 10));
                } else if (param.type === "float") {
                  set(param.name, parseFloat(e.target.value));
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
