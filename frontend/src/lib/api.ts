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
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.account_id != null) query.set("account_id", String(params.account_id));
    if (params?.symbol) query.set("symbol", params.symbol);
    if (params?.status) query.set("status", params.status);
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

  uploadCsv: async (file: File): Promise<{ upload_id: string; size_bytes: number }> => {
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
