// Storage admin panel — API response types

export interface PostgresOverview {
  version: string;
  db_size: string;
  connections: number;
}

export interface TableStat {
  name: string;
  row_count: number;
  total_size: string;
  total_size_bytes: number;
  index_size: string;
  last_vacuum: string | null;
  is_protected: boolean;
}

export interface RowsPage {
  table: string;
  page: number;
  limit: number;
  total_rows: number;
  columns: string[];
  rows: (string | null)[][];
}

export interface PurgeResult {
  table: string;
  deleted_rows: number;
  older_than_days: number;
}

export interface TruncateResult {
  table: string;
  message: string;
}

export interface QuestDBTableStat {
  name: string;
  row_count: number;
}

export interface QuestDBRowsPage {
  table: string;
  page: number;
  limit: number;
  total_rows: number;
  columns: string[];
  rows: (string | null)[][];
}

export interface DropResult {
  table: string;
  message: string;
}

export interface RedisInfo {
  status: "ok" | "unreachable";
  version: string | null;
  memory_used: string | null;
  key_count: number | null;
  uptime_seconds: number | null;
  hit_ratio: number | null;
}

export interface FlushResult {
  message: string;
  keys_flushed: number;
}
