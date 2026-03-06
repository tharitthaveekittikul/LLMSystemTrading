"use client";

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { storageApi } from "@/lib/api";
import type { RowsPage, QuestDBRowsPage } from "@/types/storage";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tableName: string;
  system: "postgres" | "questdb";
}

type PageData = RowsPage | QuestDBRowsPage;

export function TableBrowserSheet({ open, onOpenChange, tableName, system }: Props) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !tableName) return;
    setLoading(true);
    setError(null);
    const req =
      system === "postgres"
        ? storageApi.pgTableRows(tableName, page)
        : storageApi.qdbTableRows(tableName, page);
    req
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, tableName, system, page]);

  // Reset page when table changes
  useEffect(() => {
    setPage(1);
    setData(null);
  }, [tableName]);

  const totalRows = data && "total_rows" in data ? data.total_rows : null;
  const totalPages = totalRows != null ? Math.ceil(totalRows / 50) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full max-w-4xl overflow-y-auto">
        <SheetHeader className="mb-4">
          <SheetTitle className="flex items-center gap-2">
            {tableName}
            <Badge variant="outline">
              {system === "postgres" ? "PostgreSQL" : "QuestDB"}
            </Badge>
          </SheetTitle>
        </SheetHeader>

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{error}</p>}

        {data && data.rows.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="border-b bg-muted/50">
                    {data.columns.map((col) => (
                      <th
                        key={col}
                        className="px-2 py-1 text-left font-medium whitespace-nowrap"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={i} className="border-b hover:bg-muted/30">
                      {row.map((cell, j) => (
                        <td
                          key={j}
                          className="px-2 py-1 max-w-[200px] truncate text-muted-foreground"
                          title={cell ?? "null"}
                        >
                          {cell ?? (
                            <span className="italic opacity-40">null</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {totalRows != null
                  ? `Showing ${(page - 1) * 50 + 1}–${Math.min(
                      page * 50,
                      totalRows
                    )} of ${totalRows.toLocaleString()} rows`
                  : `Page ${page}`}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    totalPages != null ? page >= totalPages : data.rows.length < 50
                  }
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}

        {data && data.rows.length === 0 && (
          <p className="text-sm text-muted-foreground">Table is empty.</p>
        )}
      </SheetContent>
    </Sheet>
  );
}
