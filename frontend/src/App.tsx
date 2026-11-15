import { useEffect, useState } from "react";
import { go, parse, type Route } from "./nav";
import Ask from "./screens/Ask";
import Company from "./screens/Company";
import People, { PersonView } from "./screens/People";
import Today from "./screens/Today";

const TABS = [
  { id: "today", label: "Today" },
  { id: "ask", label: "Ask" },
  { id: "people", label: "People" },
] as const;

export default function App() {
  const [route, setRoute] = useState<Route>(() => parse(location.hash));
  const [lastTab, setLastTab] = useState<string>("today");

  useEffect(() => {
    const on = () => {
      const r = parse(location.hash);
      setRoute(r);
      if (r.tab) setLastTab(r.tab);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const active = route.tab ?? lastTab;
  return (
    <div className="min-h-dvh max-w-md mx-auto relative">
      {route.company && <Company symbol={route.company} />}
      {route.person !== undefined && <PersonView id={route.person} />}
      {route.tab === "today" && <Today />}
      {route.tab === "ask" && <Ask />}
      {route.tab === "people" && <People />}

      <nav className="fixed bottom-0 inset-x-0 z-20 bg-bg/95 backdrop-blur border-t border-line safe-b">
        <div className="max-w-md mx-auto grid grid-cols-3">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => go({ tab: t.id })}
              className={`h-12 text-sm ${active === t.id && route.tab ? "text-ink font-semibold" : "text-mute"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}
