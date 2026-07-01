export type SortState = { col: number; dir: "asc" | "desc" } | null;

export const PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
