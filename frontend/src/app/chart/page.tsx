"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

export default function ChartIndexPage() {
  const router = useRouter();

  useEffect(() => {
    const last = localStorage.getItem("lastChartSymbol") ?? "XAUUSD";
    router.replace(`/chart/${last}`);
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  );
}
