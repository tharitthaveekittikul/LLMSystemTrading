import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CpuInfo, DiskMount, GpuInfo, RamInfo } from "@/types/system";
import { Thermometer } from "lucide-react";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

function formatRate(bps: number | null): string {
  if (bps === null) return "—";
  if (bps >= 2 ** 20) return `${(bps / 2 ** 20).toFixed(1)} MB/s`;
  return `${(bps / 2 ** 10).toFixed(0)} KB/s`;
}

function pct(used: number, total: number): number {
  return total > 0 ? Math.round((used / total) * 100) : 0;
}

function barClass(percent: number): string {
  if (percent >= 80) return "bg-red-500";
  if (percent >= 60) return "bg-yellow-500";
  return "bg-green-500";
}

function MiniBar({ percent }: { percent: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${barClass(percent)}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-xs tabular-nums w-8 text-right">{percent}%</span>
    </div>
  );
}

function CpuCard({ cpu }: { cpu: CpuInfo }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">CPU</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Overall</p>
          <MiniBar percent={cpu.overall_percent} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Per Core</p>
          <div className="space-y-1">
            {cpu.per_core_percent.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-10">Core {i}</span>
                <MiniBar percent={p} />
              </div>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          {cpu.process_count} processes
          {cpu.frequency_mhz ? ` · ${(cpu.frequency_mhz / 1000).toFixed(2)} GHz` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

function RamCard({ ram }: { ram: RamInfo }) {
  const usedPct = pct(ram.used_bytes, ram.total_bytes);
  const swapPct = pct(ram.swap_used_bytes, ram.swap_total_bytes);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">RAM</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>Used</span>
            <span>{formatBytes(ram.used_bytes)} / {formatBytes(ram.total_bytes)}</span>
          </div>
          <MiniBar percent={usedPct} />
        </div>
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>Available</span>
            <span>{formatBytes(ram.available_bytes)}</span>
          </div>
        </div>
        {ram.swap_total_bytes > 0 && (
          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Swap</span>
              <span>{formatBytes(ram.swap_used_bytes)} / {formatBytes(ram.swap_total_bytes)}</span>
            </div>
            <MiniBar percent={swapPct} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DiskCard({ mounts }: { mounts: DiskMount[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Disk</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {mounts.map((m) => (
          <div key={m.mountpoint}>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span className="font-mono">{m.mountpoint}</span>
              <span>{formatBytes(m.used_bytes)} / {formatBytes(m.total_bytes)}</span>
            </div>
            <MiniBar percent={m.percent} />
          </div>
        ))}
        {mounts[0] && (
          <div className="flex gap-4 text-xs text-muted-foreground pt-1 border-t">
            <span>R: {formatRate(mounts[0].read_bytes_per_sec)}</span>
            <span>W: {formatRate(mounts[0].write_bytes_per_sec)}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GpuCard({ gpu }: { gpu: GpuInfo }) {
  const vramPct = pct(gpu.vram_used_bytes, gpu.vram_total_bytes);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">GPU — {gpu.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Utilization</p>
          <MiniBar percent={gpu.utilization_percent} />
        </div>
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>VRAM</span>
            <span>{formatBytes(gpu.vram_used_bytes)} / {formatBytes(gpu.vram_total_bytes)}</span>
          </div>
          <MiniBar percent={vramPct} />
        </div>
        {gpu.temperature_celsius !== null && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Thermometer className="h-3 w-3" />
            {gpu.temperature_celsius}°C
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface Props {
  cpu: CpuInfo;
  ram: RamInfo;
  disk: DiskMount[];
  gpu: GpuInfo | null;
}

export function HostSection({ cpu, ram, disk, gpu }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">Host</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <CpuCard cpu={cpu} />
        <RamCard ram={ram} />
        <DiskCard mounts={disk} />
        {gpu ? <GpuCard gpu={gpu} /> : (
          <Card>
            <CardContent className="p-4 text-sm text-muted-foreground">No GPU detected</CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
