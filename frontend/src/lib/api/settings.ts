import { apiRequest } from "@/lib/api";
import type { GlobalSettings } from "@/types/trading";

export interface ProviderStatus {
  provider: string;
  is_configured: boolean;
  is_active: boolean;
  key_hint: string | null;
}

export interface TaskAssignment {
  task: string;
  provider: string;
  model_name: string;
}

export const settingsApi = {
  listProviders: () =>
    apiRequest<ProviderStatus[]>("/settings/llm/providers"),

  saveProvider: (provider: string, api_key: string) =>
    apiRequest<ProviderStatus>(`/settings/llm/providers/${provider}`, {
      method: "PUT",
      body: JSON.stringify({ api_key }),
    }),

  testProvider: (provider: string, api_key: string) =>
    apiRequest<{ success: boolean; message: string }>(
      `/settings/llm/providers/${provider}/test`,
      {
        method: "POST",
        body: JSON.stringify({ api_key }),
      },
    ),

  listProviderModels: (provider: string) =>
    apiRequest<string[]>(`/settings/llm/providers/${provider}/models`),

  getAssignments: () =>
    apiRequest<TaskAssignment[]>("/settings/llm/assignments"),

  saveAssignments: (assignments: TaskAssignment[]) =>
    apiRequest<TaskAssignment[]>("/settings/llm/assignments", {
      method: "PUT",
      body: JSON.stringify({ assignments }),
    }),

  getGlobal: () =>
    apiRequest<GlobalSettings>("/settings/global"),

  patchGlobal: (body: Partial<GlobalSettings>) =>
    apiRequest<GlobalSettings>("/settings/global", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};
