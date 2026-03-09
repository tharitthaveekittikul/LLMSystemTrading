/** Root host — used for health ping and WebSocket */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Versioned REST prefix for all API calls */
export const API_V1 = `${API_BASE_URL}/api/v1`;

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_V1}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      (errorData as { detail?: string }).detail ||
        `API Error: ${response.statusText}`,
    );
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return response.json();
}

export function createWebSocket(accountId: number): WebSocket {
  return new WebSocket(`${WS_BASE_URL}/ws/dashboard/${accountId}`);
}

// ── Trades ────────────────────────────────────────────────────────────────────

export const tradesApi = {
  list: (params?: {
    account_id?: number;
    open_only?: boolean;
    date_from?: string;
    date_to?: string;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.open_only) query.set("open_only", "true");
    if (params?.date_from) query.set("date_from", params.date_from);
    if (params?.date_to) query.set("date_to", params.date_to);
    if (params?.limit != null) query.set("limit", String(params.limit));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").Trade[]>(`/trades${qs ? `?${qs}` : ""}`);
  },

  patch: (tradeId: number, body: { maintenance_enabled?: boolean }) =>
    apiRequest<{ id: number; maintenance_enabled: boolean }>(
      `/trades/${tradeId}`,
      { method: "PATCH", body: JSON.stringify(body) }
    ),
};

// ── Signals ───────────────────────────────────────────────────────────────────

export const signalsApi = {
  list: (params?: { account_id?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.limit != null) query.set("limit", String(params.limit));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").AISignal[]>(`/signals${qs ? `?${qs}` : ""}`);
  },
  analyze: (
    accountId: number,
    body: { symbol: string; timeframe: string },
  ) =>
    apiRequest<import("@/types/trading").AnalyzeResult>(`/accounts/${accountId}/analyze`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// ── Kill Switch ───────────────────────────────────────────────────────────────

export const killSwitchApi = {
  getStatus: () =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch"),
  activate: (reason: string) =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch/activate", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  deactivate: () =>
    apiRequest<import("@/types/trading").KillSwitchStatus>("/kill-switch/deactivate", {
      method: "POST",
    }),
  getLogs: () =>
    apiRequest<import("@/types/trading").KillSwitchLog[]>("/kill-switch/logs"),
};

// ── Pipeline Logs ─────────────────────────────────────────────────────────────

export const logsApi = {
  listRuns: (params?: {
    account_id?: number;
    symbol?: string;
    status?: string;
    task_type?: "signal" | "maintenance";
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.symbol) query.set("symbol", params.symbol);
    if (params?.status) query.set("status", params.status);
    if (params?.task_type) query.set("task_type", params.task_type);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").PipelineRunSummary[]>(
      `/pipeline/runs${qs ? `?${qs}` : ""}`
    );
  },

  getRun: (runId: number) =>
    apiRequest<import("@/types/trading").PipelineRunDetail>(`/pipeline/runs/${runId}`),
};

// ── Backtest ──────────────────────────────────────────────────────────────────

export const backtestApi = {
  submitRun: (req: import("@/types/trading").BacktestRunRequest) =>
    apiRequest<import("@/types/trading").BacktestRunSummary>("/backtest/runs", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  listRuns: (params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").BacktestRunSummary[]>(
      `/backtest/runs${qs ? `?${qs}` : ""}`,
    );
  },

  getRun: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestRunSummary>(`/backtest/runs/${runId}`),

  getTrades: (runId: number, params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiRequest<import("@/types/trading").BacktestTrade[]>(
      `/backtest/runs/${runId}/trades${qs ? `?${qs}` : ""}`,
    );
  },

  getEquityCurve: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestEquityPoint[]>(
      `/backtest/runs/${runId}/equity-curve`,
    ),

  getMonthlyPnl: (runId: number) =>
    apiRequest<import("@/types/trading").BacktestMonthlyPnl[]>(
      `/backtest/runs/${runId}/monthly-pnl`,
    ),

  deleteRun: (runId: number) =>
    apiRequest<void>(`/backtest/runs/${runId}`, { method: "DELETE" }),

  getAnalyticsSummary: (runId: number) =>
    apiRequest<{
      run_id: number; panel_type: string; total_trades: number | null;
      win_rate: number | null; profit_factor: number | null;
      max_drawdown_pct: number | null; sharpe_ratio: number | null; total_return_pct: number | null;
    }>(`/backtest/runs/${runId}/analytics`),

  getAnalyticsGroups: (runId: number, groupBy = "pattern_name") =>
    apiRequest<Array<{
      name: string; trades: number; win_rate: number; total_pnl: number;
      avg_win: number; avg_loss: number; profit_factor: number; best_symbol: string;
    }>>(`/backtest/runs/${runId}/analytics/groups?group_by=${groupBy}`),

  getAnalyticsHeatmap: (
    runId: number, axis1 = "symbol", axis2 = "pattern_name", metric = "win_rate"
  ) =>
    apiRequest<{ labels_x: string[]; labels_y: string[]; values: number[][] }>(
      `/backtest/runs/${runId}/analytics/heatmap?axis1=${axis1}&axis2=${axis2}&metric=${metric}`
    ),

  getAnalyticsCombinations: (runId: number, limit = 10) =>
    apiRequest<{
      top: Array<{ symbol: string; pattern: string; trades: number; win_rate: number; total_pnl: number; profit_factor: number }>;
      worst: Array<{ symbol: string; pattern: string; trades: number; win_rate: number; total_pnl: number; profit_factor: number }>;
      recommendations: string[];
    }>(`/backtest/runs/${runId}/analytics/combinations?limit=${limit}`),

  uploadCsv: async (file: File): Promise<{ upload_id: string; size_bytes: number; avg_spread_pts?: number }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_V1}/backtest/data/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(
        (err as { detail?: string }).detail || `Upload failed: ${res.statusText}`,
      );
    }
    return res.json();
  },
};

// ── Storage Admin ─────────────────────────────────────────────────────────────

export const storageApi = {
  // PostgreSQL
  pgOverview: () =>
    apiRequest<import("@/types/storage").PostgresOverview>("/storage/postgres/overview"),

  pgTables: () =>
    apiRequest<import("@/types/storage").TableStat[]>("/storage/postgres/tables"),

  pgTableRows: (tableName: string, page = 1, limit = 50) =>
    apiRequest<import("@/types/storage").RowsPage>(
      `/storage/postgres/tables/${tableName}/rows?page=${page}&limit=${limit}`
    ),

  pgPurge: (tableName: string, olderThanDays: number) =>
    apiRequest<import("@/types/storage").PurgeResult>(
      `/storage/postgres/tables/${tableName}/purge?older_than_days=${olderThanDays}`,
      { method: "DELETE" }
    ),

  pgTruncate: (tableName: string) =>
    apiRequest<import("@/types/storage").TruncateResult>(
      `/storage/postgres/tables/${tableName}/truncate`,
      { method: "DELETE" }
    ),

  // QuestDB
  qdbTables: () =>
    apiRequest<import("@/types/storage").QuestDBTableStat[]>("/storage/questdb/tables"),

  qdbTableRows: (tableName: string, page = 1, limit = 50) =>
    apiRequest<import("@/types/storage").QuestDBRowsPage>(
      `/storage/questdb/tables/${tableName}/rows?page=${page}&limit=${limit}`
    ),

  qdbDropTable: (tableName: string) =>
    apiRequest<import("@/types/storage").DropResult>(
      `/storage/questdb/tables/${tableName}`,
      { method: "DELETE" }
    ),

  // Redis
  redisInfo: () =>
    apiRequest<import("@/types/storage").RedisInfo>("/storage/redis/info"),

  redisFlush: () =>
    apiRequest<import("@/types/storage").FlushResult>("/storage/redis/flush", {
      method: "DELETE",
    }),
};

// ── LLM Usage ─────────────────────────────────────────────────────────────────

export const llmUsageApi = {
  getSummary: (period: "day" | "week" | "month" = "month") =>
    apiRequest<import("@/types/trading").LLMUsageSummary>(
      `/llm-usage/summary?period=${period}`
    ),

  getTimeseries: (params?: { granularity?: "daily" | "hourly"; days?: number }) => {
    const query = new URLSearchParams()
    if (params?.granularity) query.set("granularity", params.granularity)
    if (params?.days != null) query.set("days", String(params.days))
    const qs = query.toString()
    return apiRequest<import("@/types/trading").LLMTimeseriesPoint[]>(
      `/llm-usage/timeseries${qs ? `?${qs}` : ""}`
    )
  },

  getByModel: (period: "day" | "week" | "month" = "month") =>
    apiRequest<import("@/types/trading").LLMModelUsage[]>(
      `/llm-usage/by-model?period=${period}`
    ),

  getPricing: () =>
    apiRequest<import("@/types/trading").LLMPricingEntry[]>("/llm-usage/pricing"),
};
