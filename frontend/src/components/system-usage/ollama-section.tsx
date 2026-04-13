import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OllamaModel } from "@/types/system";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${bytes} B`;
}

interface Props {
  models: OllamaModel[];
}

export function OllamaSection({ models }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
        Ollama — Local LLMs
      </h2>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            {models.length} model{models.length !== 1 ? "s" : ""} loaded
          </CardTitle>
        </CardHeader>
        <CardContent>
          {models.length === 0 ? (
            <p className="text-sm text-muted-foreground">No models currently loaded in memory.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b">
                    <th className="text-left py-2 pr-4 font-medium">Model</th>
                    <th className="text-right py-2 pr-4 font-medium">VRAM</th>
                    <th className="text-left py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.name} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-mono text-xs">{m.name}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">
                        {formatBytes(m.size_vram_bytes)}
                      </td>
                      <td className="py-2">
                        <Badge variant="default" className="text-xs capitalize">{m.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
