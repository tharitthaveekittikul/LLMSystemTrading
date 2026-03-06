import { apiRequest } from "@/lib/api";
import type { Account, AccountCreatePayload, AccountUpdatePayload, MT5AccountInfo, AccountStats, EquityPoint, HistoryDeal, HistorySyncResult, SyncAllResult } from "@/types/trading";

export const accountsApi = {
  list: () => apiRequest<Account[]>("/accounts"),
  get: (id: number) => apiRequest<Account>(`/accounts/${id}`),
  create: (p: AccountCreatePayload) =>
    apiRequest<Account>("/accounts", {
      method: "POST",
      body: JSON.stringify(p),
    }),
  update: (id: number, p: AccountUpdatePayload) =>
    apiRequest<Account>(`/accounts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(p),
    }),
  remove: (id: number) =>
    apiRequest<void>(`/accounts/${id}`, { method: "DELETE" }),
  getInfo: (id: number) => apiRequest<MT5AccountInfo>(`/accounts/${id}/info`),
  getSymbols: (id: number, allSymbols = false): Promise<string[]> =>
    apiRequest<string[]>(`/accounts/${id}/symbols${allSymbols ? "?all_symbols=true" : ""}`),
  getEquityHistory: (id: number, hours = 24): Promise<EquityPoint[]> =>
    apiRequest<EquityPoint[]>(`/accounts/${id}/equity-history?hours=${hours}`),
  getStats: (id: number): Promise<AccountStats> =>
    apiRequest<AccountStats>(`/accounts/${id}/stats`),
  getHistory: (id: number, days?: number) =>
    apiRequest<HistoryDeal[]>(`/accounts/${id}/history?days=${days ?? 90}`),
  syncHistory: (id: number, days?: number) =>
    apiRequest<HistorySyncResult>(`/accounts/${id}/history/sync?days=${days ?? 90}`, {
      method: "POST",
    }),
  syncAll: (days?: number) =>
    apiRequest<SyncAllResult>(`/accounts/sync-all?days=${days ?? 90}`, {
      method: "POST",
    }),
};
