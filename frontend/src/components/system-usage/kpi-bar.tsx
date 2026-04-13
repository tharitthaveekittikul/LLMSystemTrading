import { Card, CardContent } from "@/components/ui/card";
import type { SystemUsage } from "@/types/system";
import { Cpu, HardDrive, MemoryStick, Microchip } from "lucide-react";

interface Props {
  data: SystemUsage;
}

function pct(used: number, total: number): number {
  return total > 0 ? Math.round((used / total) * 100) : 0;
}

function colorClass(percent: number): string {
  if (percent >= 80) return "text-red-500";
  if (percent >= 60) return "text-yellow-500";
  return "text-green-500";
}

function barClass(percent: number): string {
  if (percent >= 80) return "bg-red-500";
  if (percent >= 60) return "bg-yellow-500";
  return "bg-green-500";
}

function KpiCard({
  label,
  percent,
  sub,
  icon: Icon,
}: {
  label: string;
  percent: number;
  sub: string;
  icon: React.ElementType;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Icon className="h-4 w-4" />
            {label}
          </div>
          <span className={`text-xl font-bold tabular-nums ${colorClass(percent)}`}>
            {percent}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barClass(percent)}`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground mt-1">{sub}</p>
      </CardContent>
    </Card>
  );
}

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

export function SystemKpiBar({ data }: Props) {
  const ramPct = pct(data.ram.used_bytes, data.ram.total_bytes);
  const primaryDisk = data.disk[0];
  const diskPct = primaryDisk?.percent ?? 0;
  const gpuPct = data.gpu?.utilization_percent ?? null;
  const vramPct = data.gpu
    ? pct(data.gpu.vram_used_bytes, data.gpu.vram_total_bytes)
    : null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard
        label="CPU"
        percent={data.cpu.overall_percent}
        sub={`${data.cpu.process_count} processes${data.cpu.frequency_mhz ? ` · ${(data.cpu.frequency_mhz / 1000).toFixed(2)} GHz` : ""}`}
        icon={Cpu}
      />
      <KpiCard
        label="RAM"
        percent={ramPct}
        sub={`${formatBytes(data.ram.used_bytes)} / ${formatBytes(data.ram.total_bytes)}`}
        icon={MemoryStick}
      />
      <KpiCard
        label="Disk"
        percent={diskPct}
        sub={primaryDisk ? `${formatBytes(primaryDisk.used_bytes)} / ${formatBytes(primaryDisk.total_bytes)}` : "No disk info"}
        icon={HardDrive}
      />
      {gpuPct !== null && vramPct !== null ? (
        <KpiCard
          label="GPU"
          percent={gpuPct}
          sub={`VRAM ${vramPct}% · ${data.gpu!.name}`}
          icon={Microchip}
        />
      ) : (
        <Card>
          <CardContent className="p-4 flex items-center gap-2 text-muted-foreground">
            <Microchip className="h-4 w-4" />
            <span className="text-sm">No GPU</span>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
