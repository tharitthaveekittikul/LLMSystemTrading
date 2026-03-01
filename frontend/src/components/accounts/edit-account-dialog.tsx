"use client";

import { useEffect, useState } from "react";
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

interface EditAccountDialogProps {
  account: Account;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (account: Account) => void;
}

export function EditAccountDialog({
  account,
  open,
  onOpenChange,
  onUpdated,
}: EditAccountDialogProps) {
  const [form, setForm] = useState({
    name: account.name,
    broker: account.broker,
    server: account.server,
    mt5_path: account.mt5_path,
    is_live: String(account.is_live),
    max_lot_size: String(account.max_lot_size),
    password: "",
  });
  const [loading, setLoading] = useState(false);

  // Sync form when the dialog re-opens for a different account
  useEffect(() => {
    setForm({
      name: account.name,
      broker: account.broker,
      server: account.server,
      mt5_path: account.mt5_path,
      is_live: String(account.is_live),
      max_lot_size: String(account.max_lot_size),
      password: "",
    });
  }, [account, open]);

  function field(key: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const updated = await accountsApi.update(account.id, {
        name: form.name,
        broker: form.broker,
        server: form.server,
        ...(form.mt5_path ? { mt5_path: form.mt5_path } : {}),
        is_live: form.is_live === "true",
        max_lot_size: parseFloat(form.max_lot_size),
        ...(form.password ? { password: form.password } : {}),
      });
      toast.success(`Account "${updated.name}" updated`);
      onUpdated(updated);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update account");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Account — Login {account.login}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="edit-name">Account Name</Label>
              <Input
                id="edit-name"
                value={form.name}
                onChange={field("name")}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-broker">Broker</Label>
              <Input
                id="edit-broker"
                value={form.broker}
                onChange={field("broker")}
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-server">Server</Label>
            <Input
              id="edit-server"
              value={form.server}
              onChange={field("server")}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-mt5-path">MT5 Path</Label>
            <Input
              id="edit-mt5-path"
              placeholder="C:\Program Files\MetaTrader 5"
              value={form.mt5_path}
              onChange={field("mt5_path")}
            />
            <p className="text-xs text-muted-foreground">Leave empty to use default path</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Account Type</Label>
              <Select
                value={form.is_live}
                onValueChange={(v) => setForm((prev) => ({ ...prev, is_live: v }))}
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
              <Label htmlFor="edit-max-lot">Max Lot Size</Label>
              <Input
                id="edit-max-lot"
                type="number"
                step="0.01"
                min="0.01"
                max="100"
                value={form.max_lot_size}
                onChange={field("max_lot_size")}
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-password">
              New Password{" "}
              <span className="text-xs text-muted-foreground">(leave empty to keep current)</span>
            </Label>
            <Input
              id="edit-password"
              type="password"
              placeholder="••••••••"
              value={form.password}
              onChange={field("password")}
            />
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
              {loading ? "Saving…" : "Save Changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
