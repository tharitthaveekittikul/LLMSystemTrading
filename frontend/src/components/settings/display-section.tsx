"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { accountsApi } from "@/lib/api/accounts";
import { useSettings } from "@/hooks/use-settings";
import type { Account } from "@/types/trading";

export function DisplaySection() {
  const { defaultAccountId, setDefaultAccountId } = useSettings();
  const [accounts, setAccounts] = useState<Account[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data = await accountsApi.list();
        setAccounts(data);
      } catch {
        toast.error("Failed to load accounts");
      }
    })();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Display Preferences</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label className="text-sm">Default Account</Label>
          <p className="text-xs text-muted-foreground">
            Auto-select this account when the dashboard loads.
          </p>
          <Select
            value={defaultAccountId != null ? String(defaultAccountId) : "none"}
            onValueChange={(v) =>
              setDefaultAccountId(v === "none" ? null : Number(v))
            }
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="No default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No default — show all</SelectItem>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={String(a.id)}>
                  {a.name} ({a.broker})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}
