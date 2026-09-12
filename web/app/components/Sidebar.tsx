"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Brand from "./Brand";

/**
 * Control-centre navigation.
 *
 * Grouped by what an operator is doing rather than by our module layout: running the
 * corridor, interrogating the models, approving work, and checking the plumbing.
 * Icons are 16px line glyphs — legible at a glance, never decorative.
 */

type Item = { href: string; label: string; icon: React.ReactNode; note?: string };

const I = (d: string, extra?: React.ReactNode) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"
    style={{ flex: "none" }}>
    <path d={d} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" />
    {extra}
  </svg>
);

const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: "Control Centre",
    items: [
      { href: "/", label: "Dashboard", icon: I("M3 13h6V4H3v9zm0 7h6v-5H3v5zm11 0h7v-9h-7v9zm0-16v5h7V4h-7z") },
      { href: "/network", label: "Network", icon: I("M3 12h18M7 12V7m5 5v8m5-8V9", <circle cx="12" cy="12" r="1.6" fill="currentColor" />) },
      { href: "/maintenance", label: "Maintenance", icon: I("M4 6h16M4 12h16M4 18h10") },
      { href: "/planning", label: "Block Planning", icon: I("M4 5h16v14H4zM4 10h16M10 10v9") },
      { href: "/timetable", label: "Timetable", icon: I("M3 6h18M3 12h18M3 18h18M8 3v18M16 3v18") },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/intelligence", label: "AI Intelligence", icon: I("M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6l2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6l2.1-2.1", <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.7" />) },
      { href: "/whatif", label: "What-If Analysis", icon: I("M4 17l5-5 4 3 7-8", <circle cx="9" cy="12" r="1.4" fill="currentColor" />) },
    ],
  },
  {
    title: "Governance",
    items: [
      { href: "/approvals", label: "Approvals", icon: I("M5 12.5l4.5 4.5L19 7.5") },
      { href: "/audit", label: "Audit Trail", icon: I("M12 3l8 4v5c0 4.4-3.2 7.9-8 9-4.8-1.1-8-4.6-8-9V7l8-4zM9 12l2 2 4-4") },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/sources", label: "Data Sources", icon: I("M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3") },
      { href: "/performance", label: "Model Performance", icon: I("M4 20V10m5 10V4m5 16v-7m5 7V8") },
    ],
  },
];

export default function Sidebar() {
  const path = usePathname();

  return (
    <aside
      className="fixed inset-y-0 left-0 z-30 flex flex-col"
      style={{ width: "var(--sidebar-w)", background: "var(--chrome)" }}
    >
      <div className="flex items-center px-4"
        style={{ height: "var(--topbar-h)", borderBottom: "1px solid var(--chrome-3)" }}>
        <Link href="/" aria-label="TRACKSEN home"><Brand /></Link>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {GROUPS.map((g) => (
          <div key={g.title} className="mb-4">
            <div className="px-4 pb-1.5 sig" style={{ color: "#65788d" }}>{g.title}</div>
            {g.items.map((it) => {
              const active = path === it.href;
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  className="flex items-center gap-2.5 px-4 py-[7px] text-[12.5px] transition-colors"
                  style={{
                    color: active ? "#fff" : "var(--chrome-ink-2)",
                    background: active ? "var(--chrome-2)" : "transparent",
                    borderLeft: `2px solid ${active ? "var(--rail-2)" : "transparent"}`,
                    paddingLeft: 14,
                  }}
                >
                  <span style={{ opacity: active ? 1 : 0.75 }}>{it.icon}</span>
                  <span className={active ? "font-medium" : ""}>{it.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="px-4 py-3 text-[10px] leading-relaxed"
        style={{ borderTop: "1px solid var(--chrome-3)", color: "#65788d" }}>
        <div className="flex items-center gap-1.5 mb-1">
          <i className="lamp lamp-warn" />
          <span className="font-semibold tracking-[0.06em]" style={{ color: "#c9a227" }}>
            DEMO MODE
          </span>
        </div>
        Synthetic railway operations data.
        <br />Not an official Indian Railways product.
      </div>
    </aside>
  );
}
