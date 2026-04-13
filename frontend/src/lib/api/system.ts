import { apiRequest } from "@/lib/api";
import type { SystemUsage } from "@/types/system";

export const systemApi = {
  getUsage: () => apiRequest<SystemUsage>("/system/usage"),
};
