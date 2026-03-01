"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { killSwitchApi } from "@/lib/api";
import type { KillSwitchLog, KillSwitchStatus } from "@/types/trading";
import { formatDateTime } from "@/lib/date";

export default function KillSwitchPage() {
  const [status, setStatus] = useState<KillSwitchStatus | null>(null);
  const [logs, setLogs] = useState<KillSwitchLog[]>([]);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        killSwitchApi.getStatus(),
        killSwitchApi.getLogs(),
      ]);
      setStatus(s);
      setLogs(l);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load kill switch state",
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleActivate() {
    if (!reason.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const s = await killSwitchApi.activate(reason);
      setStatus(s);
      setReason("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Activation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeactivate() {
    setLoading(true);
    setError(null);
    try {
      const s = await killSwitchApi.deactivate();
      setStatus(s);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deactivation failed");
    } finally {
      setLoading(false);
    }
  }

  const isActive = status?.is_active ?? false;

  return (
    <SidebarInset>
      <AppHeader title="Kill Switch" />
      <div className="flex flex-1 flex-col gap-4 p-4 max-w-2xl">
        {/* Status card */}
        <Card className={isActive ? "border-destructive" : "border-green-500"}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-3">
              <div
                className={`h-4 w-4 rounded-full ${
                  isActive ? "bg-red-500 animate-pulse" : "bg-green-500"
                }`}
              />
              <span className="text-lg font-semibold">
                {isActive
                  ? "KILL SWITCH ACTIVE — All trading halted"
                  : "Kill switch inactive — Trading enabled"}
              </span>
            </div>
          </CardHeader>
          {isActive && status?.reason && (
            <CardContent className="pt-0">
              <p className="text-sm text-muted-foreground">
                Reason: {status.reason}
              </p>
              {status.activated_at && (
                <p className="text-xs text-muted-foreground mt-1">
                  Activated at {new Date(status.activated_at).toLocaleString()}
                </p>
              )}
            </CardContent>
          )}
        </Card>

        {/* Controls */}
        {isActive ? (
          <Button
            variant="default"
            className="w-full"
            onClick={handleDeactivate}
            disabled={loading}
          >
            {loading ? "Processing\u2026" : "Deactivate Kill Switch"}
          </Button>
        ) : (
          <div className="space-y-2">
            <Label htmlFor="reason">Reason for activation (required)</Label>
            <Textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Max drawdown exceeded, suspicious price action..."
              rows={3}
            />
            <Button
              variant="destructive"
              className="w-full"
              onClick={handleActivate}
              disabled={loading || !reason.trim()}
            >
              {loading ? "Processing\u2026" : "Activate Kill Switch"}
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        {/* Event log */}
        <div>
          <h3 className="text-sm font-medium mb-2">Event History</h3>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>By</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-center text-muted-foreground py-4 text-sm"
                    >
                      No events yet
                    </TableCell>
                  </TableRow>
                )}
                {logs.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell>
                      <Badge
                        variant={
                          l.action === "activated" ? "destructive" : "default"
                        }
                      >
                        {l.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {l.reason ?? "\u2014"}
                    </TableCell>
                    <TableCell className="text-sm">{l.triggered_by}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(l.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </SidebarInset>
  );
}
