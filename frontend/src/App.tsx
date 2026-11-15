import { useState } from "react";
import Today from "./screens/Today";

type Tab = "today" | "ask" | "people";

const TABS: { id: Tab; label: string; ready: boolean }[] = [
  { id: "today", label: "Today", ready: true },
  { id: "ask", label: "Ask", ready: false },
  { id: "people", label: "People", ready: false },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("today");
  return (
    <div className="min-h-dvh max-w-md mx-auto relative">
      {tab === "today" && <Today />}
      {tab !== "today" && <div className="p-8 text-center text-mute text-sm">Coming next.</div>}

      <nav className="fixed bottom-0 inset-x-0 z-20 bg-bg/95 backdrop-blur border-t border-line safe-b">
        <div className="max-w-md mx-auto grid grid-cols-3">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => t.ready && setTab(t.id)}
              className={`h-12 text-sm ${tab === t.id ? "text-ink font-semibold" : "text-mute"} ${t.ready ? "" : "opacity-40"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}
