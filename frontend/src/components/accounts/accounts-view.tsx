"use client";

import { useEffect, useState } from "react";
import { Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/lib/api/accounts";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { Account } from "@/types/trading";
import { Button } from "@/components/ui/button";
import { AccountCard } from "./account-card";
import { AddAccountDialog } from "./add-account-dialog";

export function AccountsView() {
  const { accounts, setAccounts, updateAccount, removeAccount } =
    useTradingStore();
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await accountsApi.list();
        setAccounts(data);
      } catch {
        toast.error("Failed to load accounts");
      } finally {
        setLoading(false);
      }
    })();
  }, [setAccounts]);

  function handleCreated(account: Account) {
    setAccounts([...accounts, account]);
  }

  function handleUpdated(account: Account) {
    updateAccount(account.id, account);
  }

  function handleRemoved(id: number) {
    removeAccount(id);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {loading
            ? "Loading…"
            : `${accounts.length} account${accounts.length !== 1 ? "s" : ""}`}
        </p>
        <Button size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          Add Account
        </Button>
      </div>

      {!loading && accounts.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-center">
          <Users className="mb-3 h-10 w-10 text-muted-foreground" />
          <p className="font-medium">No accounts yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add an MT5 account to get started
          </p>
          <Button
            className="mt-4"
            size="sm"
            onClick={() => setDialogOpen(true)}
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Add Account
          </Button>
        </div>
      )}

      {accounts.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {accounts.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              onUpdated={handleUpdated}
              onRemoved={handleRemoved}
            />
          ))}
        </div>
      )}

      <AddAccountDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCreated={handleCreated}
      />
    </div>
  );
}
