"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { systemApi } from "@/lib/api/system";
import { SystemKpiBar } from "@/components/system-usage/kpi-bar";
import { HostSection } from "@/components/system-usage/host-section";
import { DockerSection } from "@/components/system-usage/docker-section";
import { OllamaSection } from "@/components/system-usage/ollama-section";
import type { SystemUsage } from "@/types/system";

const POLL_INTERVAL_MS = 5_000;

const THRESHOLDS: Record<string, [number, number]> = {
  cpu: [80, 95],
  ram: [85, 95],
  disk: [85, 95],
  vram: [85, 95],
};

export default function SystemUsagePage() {
  const [data, setData] = useState<SystemUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const firedAlerts = useRef<Set<string>>(new Set());

  function checkAlerts(d: SystemUsage) {
    function fire(key: string, level: "warning" | "error", message: string) {
      if (!firedAlerts.current.has(key)) {
        firedAlerts.current.add(key);
        if (level === "error") toast.error(message);
        else toast.warning(message);
      }
    }
    function clear(...keys: string[]) {
      keys.forEach((k) => firedAlerts.current.delete(k));
    }

    const [cpuWarn, cpuCrit] = THRESHOLDS.cpu;
    if (d.cpu.overall_percent > cpuCrit) fire("cpu-crit", "error", `CPU critical: ${d.cpu.overall_percent.toFixed(1)}%`);
    else if (d.cpu.overall_percent > cpuWarn) { fire("cpu-warn", "warning", `CPU high: ${d.cpu.overall_percent.toFixed(1)}%`); clear("cpu-crit"); }
    else clear("cpu-crit", "cpu-warn");

    const [ramWarn, ramCrit] = THRESHOLDS.ram;
    const ramPct = (d.ram.used_bytes / d.ram.total_bytes) * 100;
    if (ramPct > ramCrit) fire("ram-crit", "error", `RAM critical: ${ramPct.toFixed(1)}%`);
    else if (ramPct > ramWarn) { fire("ram-warn", "warning", `RAM high: ${ramPct.toFixed(1)}%`); clear("ram-crit"); }
    else clear("ram-crit", "ram-warn");

    const [diskWarn, diskCrit] = THRESHOLDS.disk;
    const primary = d.disk[0];
    if (primary) {
      if (primary.percent > diskCrit) fire("disk-crit", "error", `Disk critical: ${primary.percent.toFixed(1)}% on ${primary.mountpoint}`);
      else if (primary.percent > diskWarn) { fire("disk-warn", "warning", `Disk high: ${primary.percent.toFixed(1)}% on ${primary.mountpoint}`); clear("disk-crit"); }
      else clear("disk-crit", "disk-warn");
    }

    if (d.gpu) {
      const [vramWarn, vramCrit] = THRESHOLDS.vram;
      const vramPct = (d.gpu.vram_used_bytes / d.gpu.vram_total_bytes) * 100;
      if (vramPct > vramCrit) fire("vram-crit", "error", `VRAM critical: ${vramPct.toFixed(1)}%`);
      else if (vramPct > vramWarn) { fire("vram-warn", "warning", `VRAM high: ${vramPct.toFixed(1)}%`); clear("vram-crit"); }
      else clear("vram-crit", "vram-warn");
    }
  }

  const fetchData = useCallback(async () => {
    try {
      const result = await systemApi.getUsage();
      setData(result);
      checkAlerts(result);
    } catch {
      // silently ignore — stale data stays visible
    } finally {
      setLoading(false);
    }
  }, []);  

  useEffect(() => {
    fetchData();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") fetchData();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <SidebarInset>
      <AppHeader
        title="System Usage"
        subtitle="Host · Docker · Ollama — refreshes every 5 s"
        showAccountSelector={false}
        showConnectionStatus={false}
        actions={
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-col gap-8 p-4 md:p-6">
        {loading && !data ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-24 rounded-lg border bg-muted/40 animate-pulse" />
            ))}
          </div>
        ) : data ? (
          <>
            <SystemKpiBar data={data} />
            <HostSection cpu={data.cpu} ram={data.ram} disk={data.disk} gpu={data.gpu} />
            {data.docker !== null && <DockerSection containers={data.docker} />}
            {data.ollama !== null && <OllamaSection models={data.ollama} />}
          </>
        ) : null}
      </div>
    </SidebarInset>
  );
}
