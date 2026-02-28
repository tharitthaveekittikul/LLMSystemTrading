"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { SidebarInset } from "@/components/ui/sidebar"
import { AppHeader } from "@/components/app-header"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Separator } from "@/components/ui/separator"
import { strategiesApi } from "@/lib/api/strategies"
import { accountsApi } from "@/lib/api/accounts"
import type { Strategy, StrategyBinding, StrategyRun, Account } from "@/types/trading"
import { ArrowLeft } from "lucide-react"

type Tab = "accounts" | "runs"

const ACTION_COLOR: Record<string, string> = {
  BUY: "text-green-600",
  SELL: "text-red-600",
  HOLD: "text-muted-foreground",
}

export default function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>()
  const strategyId = Number(id)

  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [bindings, setBindings] = useState<StrategyBinding[]>([])
  const [runs, setRuns] = useState<StrategyRun[]>([])
  const [allAccounts, setAllAccounts] = useState<Account[]>([])
  const [tab, setTab] = useState<Tab>("accounts")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      strategiesApi.get(strategyId),
      strategiesApi.bindings(strategyId),
      strategiesApi.runs(strategyId),
      accountsApi.list(),
    ]).then(([s, b, r, a]) => {
      setStrategy(s)
      setBindings(b)
      setRuns(r)
      setAllAccounts(a)
    }).catch(console.error).finally(() => setLoading(false))
  }, [strategyId])

  async function handleToggleStrategy() {
    if (!strategy) return
    const updated = await strategiesApi.update(strategy.id, { is_active: !strategy.is_active })
    setStrategy(updated)
  }

  async function handleToggleBinding(binding: StrategyBinding) {
    const updated = await strategiesApi.toggleBinding(strategyId, binding.account_id, !binding.is_active)
    setBindings(prev => prev.map(b => b.id === binding.id ? updated : b))
  }

  async function handleUnbind(binding: StrategyBinding) {
    await strategiesApi.unbind(strategyId, binding.account_id)
    setBindings(prev => prev.filter(b => b.id !== binding.id))
  }

  async function handleBind(account: Account) {
    const b = await strategiesApi.bind(strategyId, account.id)
    setBindings(prev => [...prev, b])
  }

  const boundAccountIds = new Set(bindings.map(b => b.account_id))
  const unboundAccounts = allAccounts.filter(a => !boundAccountIds.has(a.id))

  if (loading) return <SidebarInset><AppHeader title="Strategy" /><div className="p-4 text-muted-foreground">Loading...</div></SidebarInset>
  if (!strategy) return <SidebarInset><AppHeader title="Strategy" /><div className="p-4 text-muted-foreground">Strategy not found.</div></SidebarInset>

  return (
    <SidebarInset>
      <AppHeader title={strategy.name} />
      <div className="flex flex-1 flex-col gap-4 p-4 max-w-3xl mx-auto w-full">

        {/* Header */}
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/strategies"><ArrowLeft className="h-4 w-4 mr-1" />Back</Link>
          </Button>
        </div>

        <div className="rounded-lg border p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-semibold">{strategy.name}</h2>
              <Badge variant="secondary">{strategy.strategy_type}</Badge>
              <Badge variant="outline">{strategy.timeframe}</Badge>
              <Badge variant="outline">{strategy.trigger_type === "candle_close" ? "Candle close" : `Every ${strategy.interval_minutes}m`}</Badge>
            </div>
            <Switch checked={strategy.is_active} onCheckedChange={handleToggleStrategy} />
          </div>
          {strategy.description && <p className="text-sm text-muted-foreground">{strategy.description}</p>}
          <p className="text-sm text-muted-foreground">{strategy.symbols.join(", ")}</p>
        </div>

        {/* Tabs */}
        <div className="flex border-b gap-0">
          {(["accounts", "runs"] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              {t === "accounts" ? `Accounts (${bindings.length})` : `Recent Runs (${runs.length})`}
            </button>
          ))}
        </div>

        {/* Accounts tab */}
        {tab === "accounts" && (
          <div className="space-y-4">
            {bindings.length === 0 ? (
              <p className="text-sm text-muted-foreground">No accounts bound yet.</p>
            ) : (
              <div className="space-y-2">
                <p className="text-sm font-medium">Bound accounts</p>
                {bindings.map(b => {
                  const acc = allAccounts.find(a => a.id === b.account_id)
                  return (
                    <div key={b.id} className="flex items-center gap-3 rounded-lg border p-3">
                      <div className="flex-1">
                        <span className="font-medium">{b.account_name}</span>
                        {acc && <Badge variant={acc.is_live ? "destructive" : "secondary"} className="ml-2 text-xs">{acc.is_live ? "Live" : "Paper"}</Badge>}
                      </div>
                      <Switch checked={b.is_active} onCheckedChange={() => handleToggleBinding(b)} />
                      <Button variant="outline" size="sm" onClick={() => handleUnbind(b)}>Remove</Button>
                    </div>
                  )
                })}
              </div>
            )}

            {unboundAccounts.length > 0 && (
              <>
                <Separator />
                <p className="text-sm font-medium">Add account</p>
                <div className="space-y-2">
                  {unboundAccounts.map(acc => (
                    <div key={acc.id} className="flex items-center gap-3 rounded-lg border p-3">
                      <div className="flex-1">
                        <span className="font-medium">{acc.name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">#{acc.login}</span>
                        <Badge variant={acc.is_live ? "destructive" : "secondary"} className="ml-2 text-xs">{acc.is_live ? "Live" : "Paper"}</Badge>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => handleBind(acc)}>Bind</Button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Runs tab */}
        {tab === "runs" && (
          <div>
            {runs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No runs yet — the scheduler will log results here.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-left">
                      <th className="pb-2 pr-4">Signal</th>
                      <th className="pb-2 pr-4">Symbol</th>
                      <th className="pb-2 pr-4">TF</th>
                      <th className="pb-2 pr-4">Confidence</th>
                      <th className="pb-2 pr-4">Rationale</th>
                      <th className="pb-2">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map(r => (
                      <tr key={r.id} className="border-b last:border-0">
                        <td className={`py-2 pr-4 font-medium ${ACTION_COLOR[r.action] ?? ""}`}>{r.action}</td>
                        <td className="py-2 pr-4">{r.symbol}</td>
                        <td className="py-2 pr-4"><Badge variant="outline" className="text-xs">{r.timeframe}</Badge></td>
                        <td className="py-2 pr-4">{(r.confidence * 100).toFixed(0)}%</td>
                        <td className="py-2 pr-4 max-w-xs truncate text-muted-foreground">{r.reasoning}</td>
                        <td className="py-2 text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </SidebarInset>
  )
}
