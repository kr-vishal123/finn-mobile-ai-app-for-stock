/** Tiny hash router: #/today, #/ask, #/people, #/c/ASTRAL (company), #/p/12 (person). Deep-linkable. */
export type Route =
  | { tab: "today" | "ask" | "people"; company?: undefined; person?: undefined }
  | { company: string; tab?: undefined; person?: undefined }
  | { person: number; tab?: undefined; company?: undefined };

export function parse(hash: string): Route {
  const [, a, b] = hash.replace(/^#/, "").split("/");
  if (a === "c" && b) return { company: decodeURIComponent(b).toUpperCase() };
  if (a === "p" && b) return { person: Number(b) };
  if (a === "ask" || a === "people") return { tab: a };
  return { tab: "today" };
}

export function go(r: { tab?: string; company?: string; person?: number }) {
  if (r.company) location.hash = `#/c/${encodeURIComponent(r.company)}`;
  else if (r.person) location.hash = `#/p/${r.person}`;
  else location.hash = `#/${r.tab ?? "today"}`;
}
