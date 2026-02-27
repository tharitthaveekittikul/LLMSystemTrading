"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Info, Pencil, Trash2 } from "lucide-react";
import { accountsApi } from "@/lib/api/accounts";
import type { Account, MT5AccountInfo } from "@/types/trading";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { MT5InfoSheet } from "./mt5-info-sheet";
import { EditAccountDialog } from "./edit-account-dialog";

interface AccountCardProps {
  account: Account;
  onUpdated: (account: Account) => void;
  onRemoved: (id: number) => void;
}

export function AccountCard({ account, onUpdated, onRemoved }: AccountCardProps) {
  const [loadingInfo, setLoadingInfo] = useState(false);
  const [mt5Info, setMt5Info] = useState<MT5AccountInfo | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [liveInfo, setLiveInfo] = useState<MT5AccountInfo | null>(null);

  useEffect(() => {
    let isMounted = true;
    accountsApi.getInfo(account.id)
      .then((info) => { if (isMounted) setLiveInfo(info); })
      .catch(() => {}); // silently hide row if MT5 unavailable (503/502)
    return () => { isMounted = false; };
  }, [account.id]);

  async function handleGetInfo() {
    setLoadingInfo(true);
    try {
      const info = await accountsApi.getInfo(account.id);
      setMt5Info(info);
      setSheetOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to fetch MT5 info");
    } finally {
      setLoadingInfo(false);
    }
  }

  async function handleDelete() {
    try {
      await accountsApi.remove(account.id);
      toast.success(`Account "${account.name}" removed`);
      onRemoved(account.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove account");
    }
  }

  const createdAt = new Date(account.created_at).toLocaleDateString();

  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base">{account.name}</CardTitle>
            <Badge variant={account.is_live ? "destructive" : "secondary"}>
              {account.is_live ? "Live" : "Demo"}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-1 text-sm">
          <div className="flex justify-between text-muted-foreground">
            <span>Broker</span>
            <span className="text-foreground">{account.broker}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Login</span>
            <span className="font-mono text-foreground">{account.login}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Server</span>
            <span className="truncate max-w-[160px] text-foreground">{account.server}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Max Lot</span>
            <span className="text-foreground">{account.max_lot_size}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Added</span>
            <span className="text-foreground">{createdAt}</span>
          </div>
          {liveInfo && (
            <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Balance</p>
                <p className="font-medium tabular-nums">{liveInfo.balance.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Equity</p>
                <p className="font-medium tabular-nums">{liveInfo.equity.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">P&amp;L</p>
                <p className={`font-medium tabular-nums ${(liveInfo.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {(liveInfo.profit ?? 0) >= 0 ? "+" : ""}{(liveInfo.profit ?? 0).toLocaleString()}
                </p>
              </div>
            </div>
          )}
        </CardContent>

        <CardFooter className="gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={handleGetInfo}
            disabled={loadingInfo}
          >
            <Info className="mr-1.5 h-3.5 w-3.5" />
            {loadingInfo ? "Connecting…" : "MT5 Info"}
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditOpen(true)}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Remove account?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will deactivate <strong>{account.name}</strong> (login {account.login}).
                  No trades or history will be deleted.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete}>Remove</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </CardFooter>
      </Card>

      <MT5InfoSheet info={mt5Info} open={sheetOpen} onOpenChange={setSheetOpen} />
      <EditAccountDialog
        account={account}
        open={editOpen}
        onOpenChange={setEditOpen}
        onUpdated={onUpdated}
      />
    </>
  );
}
