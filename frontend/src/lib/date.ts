/**
 * Shared date formatting utilities.
 * All user-facing datetimes use: dd/MM/YYYY hh:mm:ss AM|PM
 */

const HOURS_PER_12H_CYCLE = 12;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Format any date value to "dd/MM/YYYY hh:mm:ss AM|PM".
 * Accepts ISO strings, Date objects, or millisecond timestamps.
 */
export function formatDateTime(date: Date | string | number): string {
  const d = new Date(date);
  const day = pad(d.getDate());
  const month = pad(d.getMonth() + 1);
  const year = d.getFullYear();
  let hours = d.getHours();
  const minutes = pad(d.getMinutes());
  const seconds = pad(d.getSeconds());
  const ampm = hours >= HOURS_PER_12H_CYCLE ? "PM" : "AM";
  hours = hours % HOURS_PER_12H_CYCLE || HOURS_PER_12H_CYCLE;
  return `${day}/${month}/${year} ${pad(hours)}:${minutes}:${seconds} ${ampm}`;
}

/**
 * Format any date value to "hh:mm AM|PM" (time only — for compact labels).
 */
export function formatTime(date: Date | string | number): string {
  const d = new Date(date);
  let hours = d.getHours();
  const minutes = pad(d.getMinutes());
  const ampm = hours >= HOURS_PER_12H_CYCLE ? "PM" : "AM";
  hours = hours % HOURS_PER_12H_CYCLE || HOURS_PER_12H_CYCLE;
  return `${pad(hours)}:${minutes} ${ampm}`;
}
