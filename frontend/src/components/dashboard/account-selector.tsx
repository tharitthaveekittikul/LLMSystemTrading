"use client";

import { useEffect } from "react";
import { accountsApi } from "@/lib/api/accounts";
import { useTradingStore } from "@/hooks/use-trading-store";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function AccountSelector() {
  const { accounts, activeAccountId, setAccounts, setActiveAccount } =
    useTradingStore();

  useEffect(() => {
    if (accounts.length === 0) {
      accountsApi
        .list()
        .then(setAccounts)
        .catch(() => {});
    }
  }, [accounts.length, setAccounts]);

  if (accounts.length === 0) {
    return <span className="text-xs text-muted-foreground">No accounts</span>;
  }

  return (
    <Select
      value={activeAccountId?.toString() ?? ""}
      onValueChange={(v) => setActiveAccount(Number(v))}
    >
      <SelectTrigger className="h-8 w-64 text-xs">
        <SelectValue placeholder="Select account…" />
      </SelectTrigger>
      <SelectContent>
        {accounts.map((a) => (
          <SelectItem key={a.id} value={a.id.toString()}>
            <span className="font-mono">{a.login}</span>
            <span className="ml-2 text-muted-foreground">{a.name}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
