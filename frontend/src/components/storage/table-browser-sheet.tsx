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
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Loader2,
  Database,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Search,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Copy,
  Check,
  X,
} from "lucide-react";
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
type SortState = { col: number; dir: "asc" | "desc" } | null;

const PAGE_SIZES = [25, 50, 100] as const;
type PageSize = (typeof PAGE_SIZES)[number];

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
          <div className="flex-1 overflow-auto">{tableContent}</div>
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
        <SheetBody className="p-0 overflow-auto flex-1 min-h-0">
          {tableContent}
        </SheetBody>
        <SheetFooter className="shrink-0">{footerContent}</SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/* ─── Sort icon ──────────────────────────────────────────────────────── */

function SortIcon({ col, sort }: { col: number; sort: SortState }) {
  if (!sort || sort.col !== col)
    return <ArrowUpDown className="h-3 w-3 opacity-30 shrink-0" />;
  return sort.dir === "asc" ? (
    <ArrowUp className="h-3 w-3 shrink-0" />
  ) : (
    <ArrowDown className="h-3 w-3 shrink-0" />
  );
}

/* ─── Table body ─────────────────────────────────────────────────────── */

function TableBrowserBody({
  columns,
  rows,
  loading,
  error,
  sort,
  onSort,
  copiedCell,
  onCopy,
  isFiltered,
  totalLoaded,
}: {
  columns: string[];
  rows: (string | null)[][];
  loading: boolean;
  error: string | null;
  sort: SortState;
  onSort: (col: number) => void;
  copiedCell: string | null;
  onCopy: (value: string | null, key: string) => void;
  isFiltered: boolean;
  totalLoaded: number;
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

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
        <Database className="h-10 w-10 opacity-20" />
        <p className="text-sm">
          {isFiltered && totalLoaded > 0
            ? "No rows match your filter"
            : "This table is empty"}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/40 hover:bg-muted/40 sticky top-0">
          {columns.map((col, i) => (
            <TableHead
              key={col}
              className="whitespace-nowrap text-xs font-semibold cursor-pointer select-none"
              onClick={() => onSort(i)}
            >
              <div className="flex items-center gap-1">
                {col}
                <SortIcon col={i} sort={sort} />
              </div>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, i) => (
          <TableRow key={i} className="hover:bg-muted/30">
            {row.map((cell, j) => {
              const cellKey = `${i}-${j}`;
              const isCopied = copiedCell === cellKey;
              return (
                <TableCell
                  key={j}
                  className="max-w-[200px] truncate text-xs group/cell relative cursor-pointer pr-6"
                  title={cell ?? "null"}
                  onClick={() => onCopy(cell, cellKey)}
                >
                  {cell != null ? (
                    cell
                  ) : (
                    <span className="italic text-muted-foreground/40">
                      null
                    </span>
                  )}
                  <span
                    className={`absolute right-1.5 top-1/2 -translate-y-1/2 transition-opacity ${
                      isCopied
                        ? "opacity-100"
                        : "opacity-0 group-hover/cell:opacity-50"
                    }`}
                  >
                    {isCopied ? (
                      <Check className="h-3 w-3 text-green-500" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                  </span>
                </TableCell>
              );
            })}
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
  filteredCount,
  loading,
  limit,
  pageInput,
  onPageInputChange,
  onPageJump,
  onPrev,
  onNext,
  onFirst,
  onLast,
  onLimitChange,
}: {
  page: number;
  totalRows: number | null;
  totalPages: number | null;
  rowCount: number;
  filteredCount: number | null;
  loading: boolean;
  limit: number;
  pageInput: string;
  onPageInputChange: (v: string) => void;
  onPageJump: (e: React.FormEvent) => void;
  onPrev: () => void;
  onNext: () => void;
  onFirst: () => void;
  onLast: () => void;
  onLimitChange: (v: string) => void;
}) {
  const rangeStart = (page - 1) * limit + 1;
  const rangeEnd =
    totalRows != null ? Math.min(page * limit, totalRows) : page * limit;

  const rangeLabel =
    totalRows != null
      ? `${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${totalRows.toLocaleString()}`
      : rowCount > 0
        ? `Page ${page}`
        : null;

  const canPrev = page > 1 && !loading;
  const canNext =
    !loading && (totalPages != null ? page < totalPages : rowCount >= limit);

  return (
    <div className="flex w-full items-center justify-between gap-2 flex-wrap">
      {/* Left: range + filter badge */}
      <div className="flex items-center gap-2">
        {rangeLabel && (
          <span className="text-xs text-muted-foreground">{rangeLabel}</span>
        )}
        {filteredCount != null && (
          <Badge variant="secondary" className="text-xs py-0 h-5">
            {filteredCount} match
          </Badge>
        )}
      </div>

      {/* Right: rows-per-page + navigation */}
      <div className="flex items-center gap-1.5">
        <Select value={String(limit)} onValueChange={onLimitChange}>
          <SelectTrigger className="h-8 w-auto text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZES.map((s) => (
              <SelectItem key={s} value={String(s)} className="text-xs">
                {s} / page
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={!canPrev}
            onClick={onFirst}
            className="h-8 w-8 p-0"
            title="First page"
          >
            <ChevronsLeft className="h-4 w-4" />
            <span className="sr-only">First page</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!canPrev}
            onClick={onPrev}
            className="h-8 w-8 p-0"
            title="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
            <span className="sr-only">Previous page</span>
          </Button>

          {/* Page jump input */}
          <form onSubmit={onPageJump} className="flex items-center gap-1">
            <Input
              value={pageInput}
              onChange={(e) => onPageInputChange(e.target.value)}
              placeholder={String(page)}
              className="h-8 w-14 text-center text-xs"
              inputMode="numeric"
              pattern="[0-9]*"
              title="Type a page number and press Enter"
            />
            {totalPages != null && (
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                / {totalPages}
              </span>
            )}
          </form>

          <Button
            variant="outline"
            size="sm"
            disabled={!canNext}
            onClick={onNext}
            className="h-8 w-8 p-0"
            title="Next page"
          >
            <ChevronRight className="h-4 w-4" />
            <span className="sr-only">Next page</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!canNext || totalPages == null}
            onClick={onLast}
            className="h-8 w-8 p-0"
            title="Last page"
          >
            <ChevronsRight className="h-4 w-4" />
            <span className="sr-only">Last page</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
