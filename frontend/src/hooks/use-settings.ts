import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SettingsState {
  defaultAccountId: number | null;
  setDefaultAccountId: (id: number | null) => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      defaultAccountId: null,
      setDefaultAccountId: (id) => set({ defaultAccountId: id }),
    }),
    { name: "llm-trading-settings" },
  ),
);
