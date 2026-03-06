import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PostgresOverview, QuestDBTableStat, RedisInfo } from "@/types/storage";

interface Props {
  pgOverview: PostgresOverview | null;
  pgLoading: boolean;
  qdbTables: QuestDBTableStat[] | null;
  qdbLoading: boolean;
  redisInfo: RedisInfo | null;
  redisLoading: boolean;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
    />
  );
}

export function StorageOverviewCards({
  pgOverview,
  pgLoading,
  qdbTables,
  qdbLoading,
  redisInfo,
  redisLoading,
}: Props) {
  const qdbRowTotal = qdbTables?.reduce((sum, t) => sum + t.row_count, 0) ?? 0;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {/* PostgreSQL */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            PostgreSQL
            <StatusDot ok={!!pgOverview} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {pgLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : pgOverview ? (
            <>
              <p className="text-2xl font-semibold">{pgOverview.db_size}</p>
              <p className="text-muted-foreground">{pgOverview.version}</p>
              <p className="text-muted-foreground">{pgOverview.connections} connections</p>
            </>
          ) : (
            <p className="text-xs text-destructive">Unreachable</p>
          )}
        </CardContent>
      </Card>

      {/* QuestDB */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            QuestDB
            <StatusDot ok={!!qdbTables} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {qdbLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : qdbTables ? (
            <>
              <p className="text-2xl font-semibold">{qdbTables.length} tables</p>
              <p className="text-muted-foreground">
                {qdbRowTotal.toLocaleString()} total rows
              </p>
            </>
          ) : (
            <p className="text-xs text-destructive">Unreachable</p>
          )}
        </CardContent>
      </Card>

      {/* Redis */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm font-medium">
            Redis
            <StatusDot ok={redisInfo?.status === "ok"} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {redisLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : redisInfo?.status === "ok" ? (
            <>
              <p className="text-2xl font-semibold">{redisInfo.key_count} keys</p>
              <p className="text-muted-foreground">{redisInfo.memory_used} used</p>
              <p className="text-muted-foreground">v{redisInfo.version}</p>
            </>
          ) : (
            <p className="text-xs text-destructive">Unreachable</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
