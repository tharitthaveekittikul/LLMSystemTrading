import { apiRequest } from "@/lib/api";
import type { DailyPnLResponse } from "@/types/trading";

export const analyticsApi = {
  getDaily(params: {
    year: number;
    month: number;
    accountId?: number | null;
    signal?: AbortSignal;
  }): Promise<DailyPnLResponse> {
    const q = new URLSearchParams({
      year: String(params.year),
      month: String(params.month),
    });
    if (params.accountId != null) q.set("account_id", String(params.accountId));
    return apiRequest<DailyPnLResponse>(`/analytics/daily?${q}`, {
      signal: params.signal,
    });
  },
};
