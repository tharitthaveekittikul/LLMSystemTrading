"use client";

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetBody,
  SheetFooter,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerFooter,
} from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Loader2, Database, ChevronLeft, ChevronRight } from "lucide-react";
import { storageApi } from "@/lib/api";
import type { RowsPage, QuestDBRowsPage } from "@/types/storage";
import { useIsMobile } from "@/hooks/use-mobile";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tableName: string;
  system: "postgres" | "questdb";
}

type PageData = RowsPage | QuestDBRowsPage;

export function TableBrowserSheet({
  open,
  onOpenChange,
  tableName,
  system,
}: Props) {
  const isMobile = useIsMobile();
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
  const columnCount = data?.columns.length ?? 0;

  const systemLabel = system === "postgres" ? "PostgreSQL" : "QuestDB";

  const headerContent = (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-sm">{tableName}</span>
        <Badge variant="outline" className="text-xs">
          {systemLabel}
        </Badge>
        {columnCount > 0 && (
          <Badge variant="secondary" className="text-xs">
            {columnCount} cols
          </Badge>
        )}
      </div>
    </>
  );

  const descriptionContent =
    totalRows != null
      ? `${totalRows.toLocaleString()} total rows · Page ${page}${totalPages ? ` of ${totalPages}` : ""}`
      : loading
        ? "Loading…"
        : null;

  const tableContent = (
    <TableBrowserBody
      data={data}
      loading={loading}
      error={error}
    />
  );

  const footerContent = (
    <TableBrowserFooter
      page={page}
      totalRows={totalRows}
      totalPages={totalPages}
      rowCount={data?.rows.length ?? 0}
      loading={loading}
      onPrev={() => setPage((p) => p - 1)}
      onNext={() => setPage((p) => p + 1)}
    />
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} direction="bottom">
        <DrawerContent className="max-h-[92vh] flex flex-col">
          <DrawerHeader className="border-b pb-3 text-left shrink-0">
            <DrawerTitle asChild>
              <div>{headerContent}</div>
            </DrawerTitle>
            {descriptionContent && (
              <DrawerDescription>{descriptionContent}</DrawerDescription>
            )}
          </DrawerHeader>
          <div className="flex-1 overflow-auto">{tableContent}</div>
          <div className="border-t px-4 py-3 shrink-0">{footerContent}</div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-4xl">
        <SheetHeader>
          <SheetTitle asChild>
            <div>{headerContent}</div>
          </SheetTitle>
          {descriptionContent && (
            <SheetDescription>{descriptionContent}</SheetDescription>
          )}
        </SheetHeader>
        <SheetBody className="p-0 overflow-auto">
          {tableContent}
        </SheetBody>
        <SheetFooter>{footerContent}</SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Table body ─────────────────────────────────────────────────────── */

function TableBrowserBody({
  data,
  loading,
  error,
}: {
  data: PageData | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Loading rows…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <p className="text-sm font-medium text-destructive">Failed to load</p>
        <p className="text-xs text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!data || data.rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
        <Database className="h-10 w-10 opacity-20" />
        <p className="text-sm">This table is empty</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/40 hover:bg-muted/40 sticky top-0">
          {data.columns.map((col) => (
            <TableHead
              key={col}
              className="whitespace-nowrap text-xs font-semibold"
            >
              {col}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.rows.map((row, i) => (
          <TableRow key={i} className="hover:bg-muted/30">
            {row.map((cell, j) => (
              <TableCell
                key={j}
                className="max-w-[180px] truncate text-xs"
                title={cell ?? "null"}
              >
                {cell ?? (
                  <span className="italic text-muted-foreground/50">null</span>
                )}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/* ─── Pagination footer ──────────────────────────────────────────────── */

function TableBrowserFooter({
  page,
  totalRows,
  totalPages,
  rowCount,
  loading,
  onPrev,
  onNext,
}: {
  page: number;
  totalRows: number | null;
  totalPages: number | null;
  rowCount: number;
  loading: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  const rangeStart = (page - 1) * 50 + 1;
  const rangeEnd =
    totalRows != null ? Math.min(page * 50, totalRows) : page * 50;

  const rangeLabel =
    totalRows != null
      ? `Rows ${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${totalRows.toLocaleString()}`
      : rowCount > 0
        ? `Page ${page}`
        : null;

  return (
    <div className="flex w-full items-center justify-between gap-4">
      <span className="text-xs text-muted-foreground">{rangeLabel}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 1 || loading}
          onClick={onPrev}
          className="h-8 w-8 p-0"
        >
          <ChevronLeft className="h-4 w-4" />
          <span className="sr-only">Previous page</span>
        </Button>
        <span className="min-w-[3rem] text-center text-xs text-muted-foreground">
          {page}{totalPages ? ` / ${totalPages}` : ""}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={
            loading ||
            (totalPages != null ? page >= totalPages : rowCount < 50)
          }
          onClick={onNext}
          className="h-8 w-8 p-0"
        >
          <ChevronRight className="h-4 w-4" />
          <span className="sr-only">Next page</span>
        </Button>
      </div>
    </div>
  );
}
