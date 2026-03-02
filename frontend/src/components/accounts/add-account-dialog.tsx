"use client";

import { useState } from "react";
import { toast } from "sonner";
import { accountsApi } from "@/lib/api/accounts";
import type { Account } from "@/types/trading";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface AddAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (account: Account) => void;
}

const defaultForm = {
  name: "",
  broker: "",
  login: "",
  password: "",
  server: "",
  mt5_path: "",
  is_live: "false",
  account_type: "USD",
  max_lot_size: "0.1",
  risk_pct: "1",
};

export function AddAccountDialog({
  open,
  onOpenChange,
  onCreated,
}: AddAccountDialogProps) {
  const [form, setForm] = useState(defaultForm);
  const [loading, setLoading] = useState(false);

  function field(key: keyof typeof defaultForm) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const account = await accountsApi.create({
        name: form.name,
        broker: form.broker,
        login: parseInt(form.login, 10),
        password: form.password,
        server: form.server,
        is_live: form.is_live === "true",
        allowed_symbols: [],
        max_lot_size: parseFloat(form.max_lot_size),
        risk_pct: parseFloat(form.risk_pct) / 100,
        ...(form.mt5_path ? { mt5_path: form.mt5_path } : {}),
        account_type: form.account_type,
      });
      toast.success(`Account "${account.name}" created`);
      onCreated(account);
      setForm(defaultForm);
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create account",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add MT5 Account</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">Account Name</Label>
              <Input
                id="name"
                placeholder="My ICMarkets"
                value={form.name}
                onChange={field("name")}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="broker">Broker</Label>
              <Input
                id="broker"
                placeholder="ICMarkets"
                value={form.broker}
                onChange={field("broker")}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="login">MT5 Login</Label>
              <Input
                id="login"
                type="number"
                placeholder="12345678"
                value={form.login}
                onChange={field("login")}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onChange={field("password")}
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="server">Server</Label>
            <Input
              id="server"
              placeholder="ICMarketsSC-Demo"
              value={form.server}
              onChange={field("server")}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="mt5_path">MT5 Path</Label>
            <Input
              id="mt5_path"
              placeholder="C:\Program Files\MetaTrader 5\terminal64.exe"
              value={form.mt5_path}
              onChange={field("mt5_path")}
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to use default path
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label>Account Type</Label>
              <Select
                value={form.is_live}
                onValueChange={(v) =>
                  setForm((prev) => ({ ...prev, is_live: v }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="false">Demo</SelectItem>
                  <SelectItem value="true">Live</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Currency</Label>
              <Select
                value={form.account_type}
                onValueChange={(v) =>
                  setForm((prev) => ({ ...prev, account_type: v }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="USD">USD</SelectItem>
                  <SelectItem value="USC">USC</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max_lot_size">Max Lot Size</Label>
              <Input
                id="max_lot_size"
                type="number"
                step="0.01"
                min="0.01"
                max="100"
                value={form.max_lot_size}
                onChange={field("max_lot_size")}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="risk_pct">Risk % / Trade</Label>
              <Input
                id="risk_pct"
                type="number"
                step="0.1"
                min="0.1"
                max="100"
                value={form.risk_pct}
                onChange={field("risk_pct")}
                required
              />
              <p className="text-xs text-muted-foreground">
                % of balance per trade
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Adding…" : "Add Account"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
