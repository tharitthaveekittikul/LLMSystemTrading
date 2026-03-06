"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { storageApi } from "@/lib/api";
import type { QuestDBTableStat } from "@/types/storage";
import { ConfirmDestructiveDialog } from "./confirm-destructive-dialog";
import { TableBrowserSheet } from "./table-browser-sheet";

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
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th className="px-4 py-2 text-left font-medium">Table</th>
              <th className="px-4 py-2 text-right font-medium">Rows</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {tables.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-4 py-6 text-center text-sm text-muted-foreground"
                >
                  No QuestDB tables found.
                </td>
              </tr>
            )}
            {tables.map((t) => (
              <tr key={t.name} className="border-b last:border-0 hover:bg-muted/20">
                <td
                  className="cursor-pointer px-4 py-2 font-mono text-xs hover:underline"
                  onClick={() => setBrowserTable(t.name)}
                >
                  {t.name}
                </td>
                <td className="px-4 py-2 text-right">{t.row_count.toLocaleString()}</td>
                <td className="px-4 py-2 text-right">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDropTarget(t.name)}
                  >
                    Drop
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dropTarget && (
        <ConfirmDestructiveDialog
          open={true}
          onOpenChange={(v) => { if (!v) setDropTarget(null); }}
          title={`Drop "${dropTarget}"?`}
          description={`Permanently drop QuestDB table "${dropTarget}" and all its data. Core tables are recreated on next app startup.`}
          confirmText={dropTarget}
          actionLabel="Drop Table"
          onConfirm={handleDrop}
        />
      )}

      <TableBrowserSheet
        open={!!browserTable}
        onOpenChange={(v) => { if (!v) setBrowserTable(null); }}
        tableName={browserTable ?? ""}
        system="questdb"
      />
    </div>
  );
}
