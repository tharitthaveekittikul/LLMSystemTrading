"use client";

import { useCallback, useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import { storageApi } from "@/lib/api";
import type {
  PostgresOverview,
  QuestDBTableStat,
  RedisInfo,
  TableStat,
} from "@/types/storage";
import { StorageOverviewCards } from "@/components/storage/storage-overview-cards";
import { PostgresPanel } from "@/components/storage/postgres-panel";
import { QuestDBPanel } from "@/components/storage/questdb-panel";
import { RedisPanel } from "@/components/storage/redis-panel";

export default function StoragePage() {
  const [pgOverview, setPgOverview] = useState<PostgresOverview | null>(null);
  const [pgTables, setPgTables] = useState<TableStat[]>([]);
  const [pgLoading, setPgLoading] = useState(true);

  const [qdbTables, setQdbTables] = useState<QuestDBTableStat[]>([]);
  const [qdbLoading, setQdbLoading] = useState(true);

  const [redisInfo, setRedisInfo] = useState<RedisInfo | null>(null);
  const [redisLoading, setRedisLoading] = useState(true);

  const fetchPostgres = useCallback(async () => {
    setPgLoading(true);
    try {
      const [overview, tables] = await Promise.all([
        storageApi.pgOverview(),
        storageApi.pgTables(),
      ]);
      setPgOverview(overview);
      setPgTables(tables);
    } catch {
      setPgOverview(null);
      setPgTables([]);
    } finally {
      setPgLoading(false);
    }
  }, []);

  const fetchQuestDB = useCallback(async () => {
    setQdbLoading(true);
    try {
      const tables = await storageApi.qdbTables();
      setQdbTables(tables);
    } catch {
      setQdbTables([]);
    } finally {
      setQdbLoading(false);
    }
  }, []);

  const fetchRedis = useCallback(async () => {
    setRedisLoading(true);
    try {
      const info = await storageApi.redisInfo();
      setRedisInfo(info);
    } catch {
      setRedisInfo({
        status: "unreachable",
        version: null,
        memory_used: null,
        key_count: null,
        uptime_seconds: null,
        hit_ratio: null,
      });
    } finally {
      setRedisLoading(false);
    }
  }, []);

  const refreshAll = useCallback(() => {
    fetchPostgres();
    fetchQuestDB();
    fetchRedis();
  }, [fetchPostgres, fetchQuestDB, fetchRedis]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Storage</h1>
          <p className="text-sm text-muted-foreground">
            Monitor and manage PostgreSQL, QuestDB, and Redis
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refreshAll}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <StorageOverviewCards
        pgOverview={pgOverview}
        pgLoading={pgLoading}
        qdbTables={qdbTables.length > 0 || !qdbLoading ? qdbTables : null}
        qdbLoading={qdbLoading}
        redisInfo={redisInfo}
        redisLoading={redisLoading}
      />

      <Tabs defaultValue="postgres">
        <TabsList>
          <TabsTrigger value="postgres">PostgreSQL</TabsTrigger>
          <TabsTrigger value="questdb">QuestDB</TabsTrigger>
          <TabsTrigger value="redis">Redis</TabsTrigger>
        </TabsList>

        <TabsContent value="postgres" className="mt-4">
          {pgLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <PostgresPanel tables={pgTables} onRefresh={fetchPostgres} />
          )}
        </TabsContent>

        <TabsContent value="questdb" className="mt-4">
          {qdbLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <QuestDBPanel tables={qdbTables} onRefresh={fetchQuestDB} />
          )}
        </TabsContent>

        <TabsContent value="redis" className="mt-4">
          {redisLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <RedisPanel info={redisInfo} onRefresh={fetchRedis} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
