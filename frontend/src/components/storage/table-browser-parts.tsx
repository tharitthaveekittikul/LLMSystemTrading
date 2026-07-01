import {
  Loader2,
  Database,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Copy,
  Check,
} from "lucide-react";
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
import { PAGE_SIZES, type SortState } from "@/components/storage/table-browser-types";

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

export function TableBrowserBody({
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
      <div className="flex-1 flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
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
    <div className="flex-1 min-h-0 relative [&>div]:h-full [&>div]:overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow className="hover:bg-muted/50">
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
    </div>
  );
}

/* ─── Pagination footer ──────────────────────────────────────────────── */

export function TableBrowserFooter({
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
