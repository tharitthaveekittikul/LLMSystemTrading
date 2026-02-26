import { apiRequest } from "@/lib/api";
import type { Account, AccountCreatePayload, AccountUpdatePayload, MT5AccountInfo } from "@/types/trading";

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
};
