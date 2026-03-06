"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { QuestDBTableStat } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";
import { TableBrowserSheet } from "./table-browser-sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface Props {
  tables: QuestDBTableStat[];
  onRefresh: () => void;
}

export function QuestDBPanel({ tables, onRefresh }: Props) {
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [browserTable, setBrowserTable] = useState<string | null>(null);

  const handleDrop = async () => {
    if (!dropTarget) return;
    const res = await storageApi.qdbDropTable(dropTarget);
    toast.success(res.message);
    onRefresh();
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Table</TableHead>
              <TableHead className="text-right">Rows</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tables.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="px-4 py-6 text-center text-muted-foreground"
                >
                  No QuestDB tables found.
                </TableCell>
              </TableRow>
            )}
            {tables.map((t) => (
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
                <TableCell className="text-right">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDropTarget(t.name)}
                  >
                    Drop
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {dropTarget && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => {
            if (!v) setDropTarget(null);
          }}
          title={`Drop "${dropTarget}"?`}
          description={`Permanently drop QuestDB table "${dropTarget}" and all its data. Core tables are recreated on next app startup.`}
          confirmText={dropTarget}
          actionLabel="Drop Table"
          onConfirm={handleDrop}
        />
      )}

      <TableBrowserSheet
        open={!!browserTable}
        onOpenChange={(v) => {
          if (!v) setBrowserTable(null);
        }}
        tableName={browserTable ?? ""}
        system="questdb"
      />
    </div>
  );
}
