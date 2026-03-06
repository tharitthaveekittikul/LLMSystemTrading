"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChevronDown, Lock } from "lucide-react";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { TableStat } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";
import { TableBrowserSheet } from "./table-browser-sheet";

interface Props {
  tables: TableStat[];
  onRefresh: () => void;
}

type PendingAction =
  | { kind: "truncate"; table: string }
  | { kind: "purge"; table: string; days: number };

export function PostgresPanel({ tables, onRefresh }: Props) {
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(
    null,
  );
  const [browserTable, setBrowserTable] = useState<string | null>(null);

  const handleConfirm = async () => {
    if (!pendingAction) return;
    if (pendingAction.kind === "truncate") {
      const res = await storageApi.pgTruncate(pendingAction.table);
      toast.success(res.message);
    } else {
      const res = await storageApi.pgPurge(
        pendingAction.table,
        pendingAction.days,
      );
      toast.success(
        `Purged ${res.deleted_rows.toLocaleString()} rows from ${res.table}`,
      );
    }
    onRefresh();
  };

  const purgeable = tables.filter((t) => !t.is_protected);
  const protected_ = tables.filter((t) => t.is_protected);

  return (
    <div className="space-y-6">
      {/* Manageable tables */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Manageable
        </h3>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead>Table</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Index</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {purgeable.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="px-4 py-6 text-center text-muted-foreground"
                  >
                    No manageable tables.
                  </TableCell>
                </TableRow>
              )}
              {purgeable.map((t) => (
                <TableRow key={t.name}>
                  <TableCell
                    className="cursor-pointer font-mono text-xs hover:underline"
                    onClick={() => setBrowserTable(t.name)}
                  >
                    {t.name}
                  </TableCell>
                  <TableCell className="text-right">
                    {t.row_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {t.total_size}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {t.index_size}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" size="sm">
                            Purge <ChevronDown className="ml-1 h-3 w-3" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {[30, 60, 90].map((days) => (
                            <DropdownMenuItem
                              key={days}
                              onClick={() =>
                                setPendingAction({
                                  kind: "purge",
                                  table: t.name,
                                  days,
                                })
                              }
                            >
                              Older than {days} days
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() =>
                          setPendingAction({ kind: "truncate", table: t.name })
                        }
                      >
                        Truncate
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Protected tables */}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Protected (read-only)
        </h3>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead>Table</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Index</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {protected_.map((t) => (
                <TableRow key={t.name}>
                  <TableCell
                    className="cursor-pointer font-mono text-xs hover:underline"
                    onClick={() => setBrowserTable(t.name)}
                  >
                    {t.name}
                  </TableCell>
                  <TableCell className="text-right">
                    {t.row_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {t.total_size}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {t.index_size}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant="outline" className="gap-1">
                      <Lock className="h-3 w-3" /> Protected
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Confirmation dialog */}
      {pendingAction?.kind === "truncate" && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => {
            if (!v) setPendingAction(null);
          }}
          title={`Truncate "${pendingAction.table}"?`}
          description={`Permanently delete ALL rows from ${pendingAction.table}. Cannot be undone.`}
          confirmText={pendingAction.table}
          actionLabel="Truncate"
          onConfirm={handleConfirm}
        />
      )}
      {pendingAction?.kind === "purge" && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => {
            if (!v) setPendingAction(null);
          }}
          title={`Purge "${pendingAction.table}"?`}
          description={`Delete rows older than ${pendingAction.days} days from ${pendingAction.table}.`}
          confirmText={pendingAction.table}
          actionLabel={`Purge (>${pendingAction.days}d)`}
          onConfirm={handleConfirm}
        />
      )}

      {/* Table browser */}
      <TableBrowserSheet
        open={!!browserTable}
        onOpenChange={(v) => {
          if (!v) setBrowserTable(null);
        }}
        tableName={browserTable ?? ""}
        system="postgres"
      />
    </div>
  );
}
