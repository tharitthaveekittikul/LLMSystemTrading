import { create } from "zustand";
import type {
  Account,
  AccountBalance,
  AISignal,
  KillSwitchStatus,
  Position,
} from "@/types/trading";

interface TradingState {
  // Data
  accounts: Account[];
  activeAccountId: string | null;
  balance: AccountBalance | null;
  openPositions: Position[];
  recentSignals: AISignal[];
  killSwitch: KillSwitchStatus;

  // Actions
  setAccounts: (accounts: Account[]) => void;
  setActiveAccount: (accountId: string) => void;
  setBalance: (balance: AccountBalance) => void;
  setOpenPositions: (positions: Position[]) => void;
  addSignal: (signal: AISignal) => void;
  setKillSwitch: (status: KillSwitchStatus) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  accounts: [],
  activeAccountId: null,
  balance: null,
  openPositions: [],
  recentSignals: [],
  killSwitch: { is_active: false, reason: null, triggered_at: null },

  setAccounts: (accounts) => set({ accounts }),
  setActiveAccount: (accountId) => set({ activeAccountId: accountId }),
  setBalance: (balance) => set({ balance }),
  setOpenPositions: (positions) => set({ openPositions: positions }),
  addSignal: (signal) =>
    set((state) => ({
      recentSignals: [signal, ...state.recentSignals].slice(0, 50),
    })),
  setKillSwitch: (status) => set({ killSwitch: status }),
}));
