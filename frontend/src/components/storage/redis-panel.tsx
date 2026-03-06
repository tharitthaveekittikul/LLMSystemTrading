"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { RedisInfo } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";

interface Props {
  info: RedisInfo | null;
  onRefresh: () => void;
}

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium">{value ?? "—"}</p>
    </div>
  );
}

export function RedisPanel({ info, onRefresh }: Props) {
  const [flushOpen, setFlushOpen] = useState(false);

  const handleFlush = async () => {
    const res = await storageApi.redisFlush();
    toast.success(`Redis flushed — ${res.keys_flushed} keys deleted`);
    onRefresh();
  };

  const unavailable = !info || info.status !== "ok";

  const uptimeDisplay =
    info?.uptime_seconds != null
      ? `${Math.floor(info.uptime_seconds / 3600)}h ${Math.floor(
          (info.uptime_seconds % 3600) / 60
        )}m`
      : null;

  const hitRatioDisplay =
    info?.hit_ratio != null ? `${(info.hit_ratio * 100).toFixed(1)}%` : null;

  return (
    <div className="space-y-6">
      {unavailable && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-4 text-sm text-destructive">
            Redis is unreachable. Check that the Redis container is running.
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat label="Version" value={info?.version ?? null} />
        <Stat label="Keys" value={info?.key_count ?? null} />
        <Stat label="Memory Used" value={info?.memory_used ?? null} />
        <Stat label="Uptime" value={uptimeDisplay} />
        <Stat label="Hit Ratio" value={hitRatioDisplay} />
      </div>

      <div className="border-t pt-4">
        <p className="mb-3 text-sm text-muted-foreground">
          Flush deletes all keys in the current Redis database (FLUSHDB). Rate-limit
          counters and OHLCV cache will be cleared.
        </p>
        <Button
          variant="destructive"
          disabled={unavailable}
          onClick={() => setFlushOpen(true)}
        >
          Flush DB
        </Button>
      </div>

      <ConfirmDestructiveDialog
        open={flushOpen}
        onOpenChange={setFlushOpen}
        title="Flush Redis DB?"
        description={`Delete all ${info?.key_count ?? 0} keys in the current Redis database. Rate-limit counters and OHLCV cache will be cleared.`}
        confirmText="FLUSH"
        actionLabel="Flush"
        onConfirm={handleFlush}
      />
    </div>
  );
}
