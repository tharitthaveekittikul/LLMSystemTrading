import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ContainerStat } from "@/types/system";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === "running" ? "default" : "secondary";
  return <Badge variant={variant} className="capitalize text-xs">{status}</Badge>;
}

interface Props {
  containers: ContainerStat[];
}

export function DockerSection({ containers }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
        Docker Containers
      </h2>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{containers.length} container{containers.length !== 1 ? "s" : ""}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b">
                  <th className="text-left py-2 pr-4 font-medium">Name</th>
                  <th className="text-left py-2 pr-4 font-medium">Status</th>
                  <th className="text-right py-2 pr-4 font-medium">CPU</th>
                  <th className="text-right py-2 font-medium">Memory</th>
                </tr>
              </thead>
              <tbody>
                {containers.map((c) => (
                  <tr key={c.name} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{c.name}</td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-xs">
                      {c.cpu_percent !== null ? `${c.cpu_percent.toFixed(1)}%` : "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums text-xs">
                      {c.memory_used_bytes !== null && c.memory_limit_bytes !== null
                        ? `${formatBytes(c.memory_used_bytes)} / ${formatBytes(c.memory_limit_bytes)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
