const IST = "Asia/Kolkata";

export function ago(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime();
  const m = Math.round((now - t) / 60000);
  if (m < 60) return `${Math.max(m, 1)}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.round(h / 24);
  if (d < 7) return new Date(iso).toLocaleDateString("en-IN", { weekday: "short", timeZone: IST });
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: IST });
}

export function istTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: IST,
  });
}

export function shortDay(isoDate: string): string {
  return new Date(isoDate + "T00:00:00").toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short",
  });
}
