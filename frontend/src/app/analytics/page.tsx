"use client";

import { useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { PnlCalendar } from "@/components/analytics/pnl-calendar";
import { TradeDrillDown } from "@/components/analytics/trade-drill-down";
import { MonthlyStats } from "@/components/analytics/monthly-stats";
import type { DailyEntry, DailyPnLResponse } from "@/types/trading";

export default function AnalyticsPage() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<DailyEntry | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [calData, setCalData] = useState<DailyPnLResponse | null>(null);
  const [calLoading, setCalLoading] = useState(false);

  function handleDaySelect(date: string, entry: DailyEntry) {
    setSelectedDate(date);
    setSelectedEntry(entry);
    setSheetOpen(true);
  }

  function handleDataChange(data: DailyPnLResponse | null, loading: boolean) {
    setCalData(data);
    setCalLoading(loading);
  }

  return (
    <SidebarInset>
      <AppHeader title="Analytics" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <MonthlyStats data={calData} loading={calLoading} />
        <PnlCalendar
          selectedDate={selectedDate}
          onDaySelect={handleDaySelect}
          onDataChange={handleDataChange}
        />
      </div>
      <TradeDrillDown
        date={selectedDate}
        entry={selectedEntry}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
      />
    </SidebarInset>
  );
}
