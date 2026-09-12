"use client";

import { useCallback, useEffect, useState } from "react";
import Gate from "../components/Gate";
import { usePlan } from "../components/PlanProvider";
import {
  Badge, Button, Card, DemoNote, Empty, Metric, MetricRow, PageHead,
} from "../components/ui";
import { AuditPayload, planAudit, verifyChain } from "../lib/api";
import { CURRENT_PLAN_ID } from "../lib/planId";

/**
 * Audit & Governance.
 *
 * Every transition to a plan, in order, with who did it and in what capacity. Refused
 * attempts are here too — someone reaching past their authority leaves a DENIED entry
 * rather than vanishing because the code said no.
 *
 * The chain status is the part worth understanding: each entry carries the SHA-256 of
 * the entry before it, so editing any historical record breaks every hash after it. The
 * verifier walks the chain and names the first broken link. A block plan is a safety
 * document, and a log that can be quietly rewritten answers none of the questions asked
 * after something goes wrong on the ground.
 */

const ACTION_TONE: Record<string, { color: string; bg: string }> = {
  SANCTION: { color: "var(--ok)", bg: "var(--ok-bg)" },
  CONCUR: { color: "var(--ok)", bg: "var(--ok-bg)" },
  CLEAR: { color: "var(--info)", bg: "var(--info-bg)" },
  CREATE: { color: "var(--ink-2)", bg: "var(--surface-3)" },
  MODIFY: { color: "var(--warn)", bg: "var(--warn-bg)" },
  RETURN: { color: "var(--warn)", bg: "var(--warn-bg)" },
  WITHHOLD: { color: "var(--crit)", bg: "var(--crit-bg)" },
  DENIED: { color: "var(--crit)", bg: "var(--crit-bg)" },
  SUPERSEDE: { color: "var(--ink-3)", bg: "var(--surface-3)" },
  CANCEL: { color: "var(--crit)", bg: "var(--crit-bg)" },
};

export default function AuditPage() {
  return <Gate><AuditBody /></Gate>;
}

function AuditBody() {
  const { apiUp } = usePlan();
  const [data, setData] = useState<AuditPayload | null>(null);
  const [head, setHead] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const refresh = useCallback(async () => {
    if (!apiUp) return;
    setChecking(true);
    try {
      setData(await planAudit(CURRENT_PLAN_ID));
      const v = await verifyChain();
      setHead(v?.head ?? null);
    } finally { setChecking(false); }
  }, [apiUp]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!apiUp) {
    return (
      <>
        <PageHead title="Audit & Governance"
          subtitle="Append-only, hash-chained record of every decision" />
        <Card>
          <Empty title="Solver service offline">
            The audit trail is held by the service. Start it to read and verify the chain:
            <pre className="mono text-[11px] rounded-[3px] p-3 mt-2 text-left inline-block"
              style={{ background: "var(--surface-2)" }}>python scripts/serve.py</pre>
          </Empty>
        </Card>
      </>
    );
  }

  const chain = data?.chain;
  const entries = data?.entries ?? [];
  const denied = entries.filter((e) => e.action === "DENIED").length;

  return (
    <>
      <PageHead
        title="Audit & Governance"
        subtitle={`Plan ${CURRENT_PLAN_ID} · append-only, tamper-evident`}
        right={<Button onClick={refresh} disabled={checking}>
          {checking ? "Verifying…" : "Verify chain"}
        </Button>}
      />

      {/* ---------- chain integrity ---------- */}
      <div className="mb-4 card px-4 py-3 flex items-center gap-4 flex-wrap"
        style={{ borderColor: chain?.intact === false ? "var(--crit)" : "var(--ok)" }}>
        <span className="inline-flex items-center gap-2">
          <i className="lamp" style={{
            background: chain?.intact === false ? "var(--crit)" : "var(--ok)",
            width: 9, height: 9,
          }} />
          <span className="text-[13px] font-semibold"
            style={{ color: chain?.intact === false ? "var(--crit)" : "var(--ok)" }}>
            {chain === undefined ? "Chain not yet checked"
              : chain.intact ? "Audit chain verified"
              : "Audit integrity violation detected"}
          </span>
        </span>
        <span className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>
          {chain?.intact
            ? `${chain.entries} entries, each carrying the hash of the one before it. No record has been altered.`
            : chain
            ? `Broken at entry ${chain.broken_at}: ${chain.reason}`
            : "Press verify to walk the chain."}
        </span>
        {head && (
          <span className="ml-auto mono text-[10.5px]" style={{ color: "var(--ink-3)" }}>
            head {head.slice(0, 20)}…
          </span>
        )}
      </div>

      <div className="mb-4">
        <MetricRow cols={4}>
          <Metric label="Recorded Entries" value={String(chain?.entries ?? 0)}
            compare="append-only; nothing is ever updated or deleted" />
          <Metric label="For This Plan" value={String(entries.length)} />
          <Metric label="Refused Attempts" value={String(denied)}
            tone={denied ? "crit" : "ink"}
            compare="actions blocked by the authority rules"
            hint="Someone reaching past their authority leaves a mark rather than vanishing" />
          <Metric label="Chain Status"
            value={chain?.intact === false ? "BROKEN" : chain ? "INTACT" : "—"}
            tone={chain?.intact === false ? "crit" : "ok"} />
        </MetricRow>
      </div>

      <Card title="Decision Trail" pad={false}
        subtitle="Oldest first — the order in which the plan actually moved">
        <div className="overflow-x-auto">
          <table className="ops" style={{ minWidth: 980 }}>
            <thead>
              <tr>
                <th style={{ width: 44 }}>Seq</th>
                <th style={{ width: 148 }}>Timestamp</th>
                <th style={{ width: 108 }}>Action</th>
                <th style={{ width: 128 }}>Actor</th>
                <th style={{ width: 96 }}>Role</th>
                <th>Decision / Reason</th>
                <th style={{ width: 132 }}>Entry hash</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const tone = ACTION_TONE[e.action] ?? ACTION_TONE.CREATE;
                const detail = (e.detail ?? {}) as Record<string, unknown>;
                const text = [
                  detail.remarks, detail.note, detail.reason,
                  detail.department ? `department ${detail.department}` : null,
                  detail.attempted ? `attempted ${detail.attempted}` : null,
                  Array.isArray(detail.invalidated_concurrences) &&
                    (detail.invalidated_concurrences as string[]).length
                    ? `invalidated concurrence: ${(detail.invalidated_concurrences as string[]).join(", ")}`
                    : null,
                ].filter(Boolean).join(" · ");

                return (
                  <tr key={e.seq}>
                    <td className="tnum text-[11px]" style={{ color: "var(--ink-3)" }}>{e.seq}</td>
                    <td className="tnum text-[11px]">{e.timestamp.slice(0, 19).replace("T", " ")}</td>
                    <td><Badge color={tone.color} bg={tone.bg}>{e.action}</Badge></td>
                    <td className="text-[11.5px]">{e.actor}</td>
                    <td className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>{e.role}</td>
                    <td className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {text || "—"}
                    </td>
                    <td className="mono text-[10px]" style={{ color: "var(--ink-3)" }}
                      title={e.entry_hash}>
                      {e.entry_hash.slice(0, 14)}…
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {entries.length === 0 && (
            <Empty title="Nothing recorded for this plan yet">
              Submit it from Approval Control and every step from there will appear here.
            </Empty>
          )}
        </div>
      </Card>

      <p className="text-[10.5px] mt-4 leading-relaxed max-w-3xl" style={{ color: "var(--ink-3)" }}>
        Each entry contains the SHA-256 of the entry before it. Altering any historical
        record — a name, a remark, a sanction time — changes its hash and breaks every
        link after it, which the verifier detects and locates. The trail is persisted to
        disk, so it survives a restart of the service.
      </p>
    </>
  );
}
