"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
} from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Search, X } from "lucide-react";
import { storageApi } from "@/lib/api";
import type { RowsPage, QuestDBRowsPage } from "@/types/storage";
import { useIsMobile } from "@/hooks/use-mobile";
import { TableBrowserBody, TableBrowserFooter } from "@/components/storage/table-browser-parts";
import { type PageSize, type SortState } from "@/components/storage/table-browser-types";

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
  const [limit, setLimit] = useState<PageSize>(50);
  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState>(null);
  const [pageInput, setPageInput] = useState("");
  const [copiedCell, setCopiedCell] = useState<string | null>(null);

  // Reset UI state when tableName prop changes (adjusting state during render — React docs pattern)
  const [prevTableName, setPrevTableName] = useState(tableName);
  if (prevTableName !== tableName) {
    setPrevTableName(tableName);
    setPage(1);
    setData(null);
    setSearch("");
    setSort(null);
    setPageInput("");
  }

  // Fetch rows — setState only inside callbacks, not the effect body directly
  const triggerFetch = useCallback(() => {
    setLoading(true);
    setError(null);
    const req =
      system === "postgres"
        ? storageApi.pgTableRows(tableName, page, limit)
        : storageApi.qdbTableRows(tableName, page, limit);
    req
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [system, tableName, page, limit]);

  useEffect(() => {
    if (!open) return;
    triggerFetch(); // eslint-disable-line react-hooks/set-state-in-effect
  }, [open, triggerFetch]);

  const totalRows = data && "total_rows" in data ? data.total_rows : null;
  const totalPages = totalRows != null ? Math.ceil(totalRows / limit) : null;

  const filteredRows = useMemo(() => {
    if (!data) return [];
    if (!search.trim()) return data.rows;
    const q = search.toLowerCase();
    return data.rows.filter((row) =>
      row.some((cell) => cell != null && cell.toLowerCase().includes(q)),
    );
  }, [data, search]);

  const displayRows = useMemo(() => {
    if (!sort) return filteredRows;
    return [...filteredRows].sort((a, b) => {
      const av = a[sort.col] ?? "";
      const bv = b[sort.col] ?? "";
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [filteredRows, sort]);

  const handleSort = (colIdx: number) =>
    setSort((prev) => {
      if (!prev || prev.col !== colIdx) return { col: colIdx, dir: "asc" };
      if (prev.dir === "asc") return { col: colIdx, dir: "desc" };
      return null;
    });

  const handleCopy = async (value: string | null, cellKey: string) => {
    await navigator.clipboard.writeText(value ?? "");
    setCopiedCell(cellKey);
    setTimeout(() => setCopiedCell(null), 1500);
  };

  const handlePageJump = (e: React.FormEvent) => {
    e.preventDefault();
    const n = parseInt(pageInput, 10);
    if (!isNaN(n) && n >= 1 && (totalPages == null || n <= totalPages)) {
      setPage(n);
    }
    setPageInput("");
  };

  const handleLimitChange = (val: string) => {
    setLimit(parseInt(val) as PageSize);
    setPage(1);
  };

  const systemLabel = system === "postgres" ? "PostgreSQL" : "QuestDB";
  const columnCount = data?.columns.length ?? 0;

  const descriptionText =
    totalRows != null
      ? `${totalRows.toLocaleString()} rows · Page ${page}${totalPages ? ` of ${totalPages}` : ""}`
      : loading
        ? "Loading…"
        : null;

  const titleContent = (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="font-mono text-sm font-semibold">{tableName}</span>
      <Badge variant="outline" className="text-xs">
        {systemLabel}
      </Badge>
      {columnCount > 0 && (
        <Badge variant="secondary" className="text-xs">
          {columnCount} cols
        </Badge>
      )}
      {totalRows != null && (
        <Badge variant="secondary" className="text-xs">
          {totalRows.toLocaleString()} rows
        </Badge>
      )}
    </div>
  );

  const searchBar = (
    <div className="relative">
      <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
      <Input
        placeholder="Filter rows on this page…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="h-8 pl-8 pr-8 text-xs"
      />
      {search && (
        <button
          className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
          onClick={() => setSearch("")}
          aria-label="Clear filter"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );

  const tableContent = (
    <TableBrowserBody
      columns={data?.columns ?? []}
      rows={displayRows}
      loading={loading && !data}
      error={error}
      sort={sort}
      onSort={handleSort}
      copiedCell={copiedCell}
      onCopy={handleCopy}
      isFiltered={!!search}
      totalLoaded={data?.rows.length ?? 0}
    />
  );

  const footerContent = (
    <TableBrowserFooter
      page={page}
      totalRows={totalRows}
      totalPages={totalPages}
      rowCount={data?.rows.length ?? 0}
      filteredCount={search ? filteredRows.length : null}
      loading={loading}
      limit={limit}
      pageInput={pageInput}
      onPageInputChange={setPageInput}
      onPageJump={handlePageJump}
      onPrev={() => setPage((p) => p - 1)}
      onNext={() => setPage((p) => p + 1)}
      onFirst={() => setPage(1)}
      onLast={() => totalPages && setPage(totalPages)}
      onLimitChange={handleLimitChange}
    />
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} direction="bottom">
        <DrawerContent className="max-h-[92vh] flex flex-col">
          <DrawerHeader className="border-b pb-3 text-left shrink-0 space-y-2">
            <DrawerTitle asChild>
              <div>{titleContent}</div>
            </DrawerTitle>
            {descriptionText && (
              <DrawerDescription>{descriptionText}</DrawerDescription>
            )}
            {searchBar}
          </DrawerHeader>
          <div className="flex-1 min-h-0 flex flex-col">{tableContent}</div>
          <div className="border-t px-4 py-3 shrink-0">{footerContent}</div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-4xl flex flex-col">
        <SheetHeader className="shrink-0 space-y-2">
          <SheetTitle asChild>
            <div>{titleContent}</div>
          </SheetTitle>
          {descriptionText && (
            <SheetDescription>{descriptionText}</SheetDescription>
          )}
          <div>{searchBar}</div>
        </SheetHeader>
        <SheetBody className="p-0 flex-1 min-h-0 flex flex-col">
          {tableContent}
        </SheetBody>
        <SheetFooter className="shrink-0">{footerContent}</SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

