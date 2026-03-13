import { create } from "zustand";
import type {
  Account,
  AccountBalance,
  AISignal,
  KillSwitchStatus,
  PendingOrder,
  Position,
} from "@/types/trading";

interface TradingState {
  // Data
  accounts: Account[];
  activeAccountId: number | null;
  balance: AccountBalance | null;
  openPositions: Position[];
  pendingOrders: PendingOrder[];
  recentSignals: AISignal[];
  killSwitch: KillSwitchStatus;

  // Actions
  setAccounts: (accounts: Account[]) => void;
  setActiveAccount: (accountId: number | null) => void;
  updateAccount: (id: number, updates: Partial<Account>) => void;
  removeAccount: (id: number) => void;
  setBalance: (balance: AccountBalance) => void;
  setOpenPositions: (positions: Position[]) => void;
  setPendingOrders: (orders: PendingOrder[]) => void;
  addSignal: (signal: AISignal) => void;
  setKillSwitch: (status: KillSwitchStatus) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  accounts: [],
  activeAccountId: null,
  balance: null,
  openPositions: [],
  pendingOrders: [],
  recentSignals: [],
  killSwitch: { is_active: false, reason: null, activated_at: null },

  setAccounts: (accounts) => set({ accounts }),
  setActiveAccount: (accountId) => set({ activeAccountId: accountId }),
  updateAccount: (id, updates) =>
    set((state) => ({
      accounts: state.accounts.map((a) => (a.id === id ? { ...a, ...updates } : a)),
    })),
  removeAccount: (id) =>
    set((state) => ({
      accounts: state.accounts.filter((a) => a.id !== id),
      activeAccountId: state.activeAccountId === id ? null : state.activeAccountId,
    })),
  setBalance: (balance) => set({ balance }),
  setOpenPositions: (positions) => set({ openPositions: positions }),
  setPendingOrders: (orders) => set({ pendingOrders: orders }),
  addSignal: (signal) =>
    set((state) => ({
      recentSignals: [signal, ...state.recentSignals].slice(0, 50),
    })),
  setKillSwitch: (status) => set({ killSwitch: status }),
}));
