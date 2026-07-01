import {
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Square,
  ShieldCheck,
  Filter,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { OptimizationResult } from "@/types/trading";
import { qualityScore, THRESHOLDS, fmt } from "@/lib/optimize-result-utils";

export function StatusBadge({ status }: { status: string }) {
  if (status === "completed") return <Badge className="gap-1 bg-green-500/15 text-green-700 dark:text-green-400 border-green-500/30"><CheckCircle2 className="h-3 w-3" />Completed</Badge>;
  if (status === "failed") return <Badge variant="destructive" className="gap-1"><XCircle className="h-3 w-3" />Failed</Badge>;
  if (status === "running") return <Badge className="gap-1 bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30"><Loader2 className="h-3 w-3 animate-spin" />Running</Badge>;
  if (status === "cancelling") return <Badge className="gap-1 bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/30"><Loader2 className="h-3 w-3 animate-spin" />Stopping…</Badge>;
  if (status === "cancelled") return <Badge className="gap-1 bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/30"><Square className="h-3 w-3 fill-current" />Stopped</Badge>;
  return <Badge variant="outline" className="gap-1"><Clock className="h-3 w-3" />Pending</Badge>;
}

export function QualityBadge({ metrics }: { metrics: { [key: string]: number | null } }) {
  const { passed, total, allPassed } = qualityScore(metrics);
  const failedLabels = Object.entries(THRESHOLDS)
    .filter(([key, t]) => {
      const v = metrics[key];
      if (v == null) return false;
      return t.lowerIsBetter ? v > t.value : v < t.value;
    })
    .map(([, t]) => t.label);

  if (allPassed) {
    return (
      <span title={`All ${total} criteria passed`} className="inline-flex items-center gap-1 text-green-600 dark:text-green-400 font-semibold text-xs">
        <ShieldCheck className="h-3.5 w-3.5" />
        {passed}/{total}
      </span>
    );
  }
  return (
    <span title={`Failed: ${failedLabels.join(", ")}`} className={`inline-flex items-center gap-1 text-xs font-mono ${passed >= total - 1 ? "text-yellow-600 dark:text-yellow-400" : "text-muted-foreground"}`}>
      <Filter className="h-3 w-3" />
      {passed}/{total}
    </span>
  );
}

export function MetricCell({
  metricKey,
  value,
  isOptimizeTarget,
  rank,
}: {
  metricKey: string;
  value: number | null;
  isOptimizeTarget: boolean;
  rank: number;
  allResults: OptimizationResult[];
}) {
  const bestRank = 0;
  const isTop = rank === bestRank;

  return (
    <td
      className={`px-3 py-2 text-right font-mono tabular-nums ${
        isOptimizeTarget && isTop
          ? "text-green-600 dark:text-green-400 font-semibold"
          : isOptimizeTarget
          ? "text-foreground"
          : "text-muted-foreground"
      }`}
    >
      {fmt(value, metricKey)}
    </td>
  );
}
