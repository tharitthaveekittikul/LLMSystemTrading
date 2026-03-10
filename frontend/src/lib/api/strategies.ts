import { apiRequest } from "@/lib/api"
import type { Strategy, StrategyBinding, CreateStrategyPayload, StrategyRun, StrategyStats } from "@/types/trading"

export const strategiesApi = {
  list: () => apiRequest<Strategy[]>("/strategies"),
  get: (id: number) => apiRequest<Strategy>(`/strategies/${id}`),
  create: (payload: CreateStrategyPayload) =>
    apiRequest<Strategy>("/strategies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: number, payload: Partial<CreateStrategyPayload> & { is_active?: boolean }) =>
    apiRequest<Strategy>(`/strategies/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  delete: (id: number) =>
    apiRequest<void>(`/strategies/${id}`, { method: "DELETE" }),
  bind: (id: number, account_id: number, is_active = true) =>
    apiRequest<StrategyBinding>(`/strategies/${id}/bind`, {
      method: "POST",
      body: JSON.stringify({ account_id, is_active }),
    }),
  unbind: (id: number, account_id: number) =>
    apiRequest<void>(`/strategies/${id}/bind/${account_id}`, { method: "DELETE" }),
  toggleBinding: (id: number, account_id: number, is_active: boolean) =>
    apiRequest<StrategyBinding>(`/strategies/${id}/bind/${account_id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active }),
    }),
  runs: (id: number) => apiRequest<StrategyRun[]>(`/strategies/${id}/runs`),
  bindings: (id: number) => apiRequest<StrategyBinding[]>(`/strategies/${id}/bindings`),
  getStats: (id: number) => apiRequest<StrategyStats>(`/strategies/${id}/stats`),
  trigger: (id: number) => apiRequest<{ message: string }>(`/strategies/${id}/trigger`, { method: "POST" }),
}
