import type { EconomicEvent } from "@/types/trading";

/** Convert UTC ISO string to Bangkok (UTC+7) display string */
export function toBangkok(utcStr: string, opts?: Intl.DateTimeFormatOptions): string {
  return new Date(utcStr).toLocaleString("en-GB", {
    timeZone: "Asia/Bangkok",
    hour12: false,
    ...opts,
  });
}

export function toBangkokDate(utcStr: string): string {
  return toBangkok(utcStr, {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

export function toBangkokTime(utcStr: string): string {
  return toBangkok(utcStr, { hour: "2-digit", minute: "2-digit" });
}

/** Group events by their Bangkok calendar date */
export function groupByDate(events: EconomicEvent[]): Map<string, EconomicEvent[]> {
  const map = new Map<string, EconomicEvent[]>();
  for (const ev of events) {
    const key = toBangkokDate(ev.event_utc);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(ev);
  }
  return map;
}

export function isPast(utcStr: string): boolean {
  return new Date(utcStr) < new Date();
}
