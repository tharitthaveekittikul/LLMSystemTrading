"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";

export default function ChartIndexPage() {
  const router = useRouter();

  useEffect(() => {
    const last = localStorage.getItem("lastChartSymbol") ?? "XAUUSD";
    router.replace(`/chart/${last}`);
  }, [router]);

  return (
    <SidebarInset className="flex items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </SidebarInset>
  );
}
