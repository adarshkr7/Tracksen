"use client";

import { useCallback, useEffect, useState } from "react";
import Gate from "../components/Gate";
import { usePlan } from "../components/PlanProvider";
import {
  Badge, Button, Card, DemoNote, Empty, Lamp, Metric, MetricRow, PageHead,
} from "../components/ui";
import { SourcesPayload, sources as fetchSources } from "../lib/api";

/**
 * Data Integration Status.
 *
 * Live adapter state, queried from the ingestion service. Each departmental system is
 * tried REST → read-only DB view → CSV drop and falls back, so "connected" alone would
 * hide the interesting part: *which* mode answered, and why the better ones did not.
 *
 * The feeds behind these adapters are synthetic. The transport, the schema translation
 * and the failure handling are real; the data is not, and this screen says so rather
 * than letting a viewer assume a live departmental connection.
 */

const SYSTEM_META: Record<string, { dept: string; native: string }> = {
  TMS: { dept: "Engineering (P.Way)", native: "UPPER_SNAKE · km · DD-MM-YYYY · S1–S5" },
  SMMS: { dept: "Signal & Telecom", native: "lower_snake · metres · ISO · P1–P5 (P1 worst)" },
  TDMS: { dept: "Traction Distribution", native: "camelCase · nested km · ISO-8601 Z · 1–5" },
};

const MODE_LABEL: Record<string, string> = {
  rest: "REST endpoint",
  db_view: "Read-only DB view",
  csv: "CSV drop",
  unavailable: "No mode available",
};

export default function SourcesPage() {
  return <Gate><SourcesBody /></Gate>;
}

function SourcesBody() {
  const { apiUp } = usePlan();
  const [data, setData] = useState<SourcesPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!apiUp) return;
    setLoading(true);
    try { setData(await fetchSources()); } finally { setLoading(false); }
  }, [apiUp]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!apiUp) {
    return (
      <>
        <PageHead title="Data Integration Status"
          subtitle="TMS · SMMS · TDMS · Control Office" />
        <Card>
          <Empty title="Solver service offline">
            Adapter status is queried live from the ingestion service. Start it to see
            which mode each departmental system answered on:
            <pre className="mono text-[11px] rounded-[3px] p-3 mt-2 text-left inline-block"
              style={{ background: "var(--surface-2)" }}>python scripts/serve.py</pre>
          </Empty>
        </Card>
      </>
    );
  }

  const rows = data?.sources ?? [];
  const connected = rows.filter((r) => r.connected).length;
  const degraded = rows.filter((r) => r.degraded && r.connected).length;
  const rejected = rows.reduce((s, r) => s + r.rejected.length, 0);

  return (
    <>
      <PageHead
        title="Data Integration Status"
        subtitle="Each source tried REST → read-only DB view → CSV drop, and falls back"
        right={<Button onClick={refresh} disabled={loading}>
          {loading ? "Querying…" : "Re-query adapters"}
        </Button>}
      />
      <div className="mb-4">
        <DemoNote>
          {data?.note ?? "Synthetic feeds; TRACKSEN is not connected to live Indian Railways systems."}
          {" "}The adapters, their fallback ladder and their failure handling are real.
        </DemoNote>
      </div>

      <TimetableSource />

      <div className="mb-4">
        <MetricRow cols={4}>
          <Metric label="Systems Connected" value={`${connected} / ${rows.length || 3}`}
            tone={connected === rows.length && rows.length ? "ok" : "warn"} />
          <Metric label="Running Degraded" value={String(degraded)}
            tone={degraded ? "warn" : "ink"}
            compare="fell back from REST — still fully functional" />
          <Metric label="Unified Tasks" value={String(data?.unified_tasks ?? 0)}
            compare="normalised into one task model" />
          <Metric label="Records Rejected" value={String(rejected)}
            tone={rejected ? "crit" : "ok"}
            compare="rejected by name, never silently dropped" />
        </MetricRow>
      </div>

      <div className="space-y-4">
        {rows.map((r) => {
          const meta = SYSTEM_META[r.system];
          return (
            <Card key={r.system} pad={false}
              title={`${r.system} — ${meta?.dept ?? ""}`}
              subtitle={meta ? `Native schema: ${meta.native}` : undefined}
              right={
                <>
                  {r.degraded && r.connected && (
                    <Badge color="var(--warn)" bg="var(--warn-bg)">DEGRADED</Badge>
                  )}
                  <Lamp state={r.connected ? "ok" : "crit"} live={r.connected}
                    label={r.connected ? "Connected" : "Unavailable"} />
                </>
              }
            >
              <div className="grid gap-px" style={{ background: "var(--line)" }}>
                <div className="grid gap-px"
                  style={{ background: "var(--line)", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))" }}>
                  <Cell label="Answering on" value={MODE_LABEL[r.mode] ?? r.mode}
                    tone={r.mode === "rest" ? "var(--ok)" : "var(--ink)"} />
                  <Cell label="Records fetched" value={String(r.fetched)} />
                  <Cell label="Accepted" value={String(r.accepted)} tone="var(--ok)" />
                  <Cell label="Rejected" value={String(r.rejected.length)}
                    tone={r.rejected.length ? "var(--crit)" : "var(--ink-3)"} />
                  <Cell label="Duplicates" value={String(r.duplicates)} />
                </div>
              </div>

              {/* The fallback ladder, and why each rung was skipped. */}
              <div className="px-3.5 py-3" style={{ borderTop: "1px solid var(--line)" }}>
                <div className="sig mb-2">Connection ladder</div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {["rest", "db_view", "csv"].map((mode, i) => {
                    const tried = r.attempted.includes(mode);
                    const used = r.mode === mode;
                    const why = r.skipped?.[mode];
                    return (
                      <span key={mode} className="flex items-center gap-1.5">
                        <span
                          title={why ?? (used ? "in use" : tried ? "" : "not attempted")}
                          className="rounded-[3px] border px-2 py-[3px] text-[11px]"
                          style={{
                            borderColor: used ? "var(--ok)" : "var(--line-2)",
                            background: used ? "var(--ok-bg)" : "var(--surface-2)",
                            color: used ? "var(--ok)" : tried ? "var(--ink-3)" : "var(--line-3)",
                            textDecoration: why ? "line-through" : undefined,
                          }}>
                          {MODE_LABEL[mode]}
                        </span>
                        {i < 2 && <span style={{ color: "var(--line-2)" }}>→</span>}
                      </span>
                    );
                  })}
                </div>
                {Object.entries(r.skipped ?? {}).map(([mode, why]) => (
                  <div key={mode} className="text-[10.5px] mt-1.5" style={{ color: "var(--ink-3)" }}>
                    <b>{MODE_LABEL[mode]}</b> skipped — {why}
                  </div>
                ))}
                {r.rejected.length > 0 && (
                  <div className="mt-2 text-[11px]" style={{ color: "var(--crit)" }}>
                    {r.rejected.slice(0, 4).map((x, i) => <div key={i}>{x}</div>)}
                  </div>
                )}
              </div>
            </Card>
          );
        })}

        <Card title="Control Office (COA)"
          subtitle="Working timetable, goods forecast and mandated corridor windows"
          right={<Lamp state="ok" label="Timetable loaded" />}>
          <p className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>
            Coaching paths are deterministic and read off the working timetable. Goods is
            forecast, so each path carries a probability — which is why the traffic cost
            of an hour is an expectation rather than a count.
          </p>
        </Card>
      </div>

      <p className="text-[10.5px] mt-4 leading-relaxed max-w-3xl" style={{ color: "var(--ink-3)" }}>
        Nothing is ever written to a source system. The database adapter opens read-only
        and refuses anything but a view — a DBA grants a view, not a table, and the code
        should make the weaker grant sufficient.
      </p>
    </>
  );
}

function Cell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="px-3.5 py-2.5" style={{ background: "var(--surface)" }}>
      <div className="sig">{label}</div>
      <div className="tnum text-[15px] font-semibold mt-1"
        style={{ color: tone ?? "var(--ink)" }}>{value}</div>
    </div>
  );
}

/**
 * Which coaching timetable is in force.
 *
 * The repository ships an approximate file so it runs without a multi-hour crawl, and
 * picks up a railpull import automatically when one exists. Those two are not equally
 * trustworthy, so the screen says which is loaded rather than leaving a viewer to assume
 * the better one.
 */
function TimetableSource() {
  const { plan } = usePlan();
  const tt = plan?.timetable;
  if (!tt) return null;

  return (
    <div className="mb-4">
      <Card pad={false}
        title="Coaching Timetable"
        subtitle={`${tt.services} booked services · ${tt.file}`}
        right={
          <Lamp state={tt.imported ? "ok" : "warn"}
            label={tt.imported ? "Imported from NTES" : "Approximate times"} />
        }
      >
        <div className="px-4 py-3 text-[12px] leading-relaxed"
          style={{ color: "var(--ink-2)" }}>
          {tt.imported ? (
            <>
              Train numbers, booked times and running days come from NTES via a local
              railpull crawl. These are published times, not estimates.
            </>
          ) : (
            <>
              Train numbers, names and the road each service works are real. The
              <b> times and running days are approximate</b> — plausible slots consistent
              with each service&rsquo;s published pattern, not read off the Working Time
              Table. Goods is absent by design: goods paths are not booked, so TRACKSEN
              forecasts them.
              <div className="mt-2.5 pt-2.5" style={{ borderTop: "1px solid var(--line)" }}>
                To run on published times instead, crawl once with{" "}
                <a href="https://github.com/shwetankg07/railpull" target="_blank"
                  rel="noreferrer noopener"
                  style={{ color: "var(--rail)", textDecoration: "underline" }}>
                  railpull
                </a>{" "}and import it. The importer writes the file the loader prefers, so
                nothing else has to change:
                <pre className="mono text-[11px] rounded-[3px] p-2.5 mt-2 overflow-x-auto"
                  style={{ background: "var(--surface-2)" }}>
python scripts/import_railpull.py --railpull ../railpull/data \
  -o data/timetable_danapur.imported.csv</pre>
                That file is git-ignored: railpull asks that NTES data not be
                redistributed, so it stays a local working file.
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
