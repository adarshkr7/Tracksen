# TRACKSEN — architecture

Three diagrams. The first is the whole system; the other two are the subsystems that do not
fit cleanly inside a data-flow picture because they are about *authority* and *degradation*
rather than about data moving.

Read [README.md](../README.md) for what each module does and
[AUDIT.md](AUDIT.md) for which parts of this are load-bearing and which are stand-ins.

---

## 1. The whole system

Everything flows one way: three departmental systems are read, never written; their records
become one task model keyed by chainage; models score that model; the solver places blocks
into windows priced against real train paths; and the plan comes out the far end as a
recommendation that a person still has to sanction.

```mermaid
flowchart TB

    subgraph SRC["1 · Source systems — read-only, never written to"]
        direction LR
        TMS["<b>TMS</b> · Track Management System<br/>Engineering / P.Way<br/><i>UPPER_SNAKE · km · DD-MM-YYYY · S1–S5</i>"]
        SMMS["<b>SMMS</b> · Signalling Maintenance Mgmt<br/>Signal & Telecom<br/><i>lower_snake · metres · ISO · P1–P5, P1 worst</i>"]
        TDMS["<b>TDMS</b> · Traction Distribution Mgmt<br/>OHE<br/><i>camelCase · nested km · ISO-8601Z · 1–5</i>"]
        COA["<b>COA</b> · Control Office<br/>working timetable + goods forecast"]
    end

    subgraph ING["2 · Ingestion — ingestion/adapters.py"]
        direction LR
        LADDER{"fidelity ladder<br/>REST → read-only DB view → CSV drop"}
        NORM["normalise · dedupe · reject by name<br/><i>metres→km, P-scale inversion, date formats</i>"]
    end

    UTM["<b>3 · Unified Task Model</b> — domain.py<br/>every task keyed by (section, line, chainage km)<br/><i>the key that makes clubbing arithmetic</i>"]

    subgraph NET["4 · Network & traffic — network.py, models/traffic.py"]
        direction LR
        TOPO["Danapur division topology<br/>main line + 8 branches, 41 sections"]
        TT["timetable → path occupations<br/>543 services + forecast goods"]
        CORR["corridor regime<br/><i>single-240 · split-150x2 · min-180</i><br/>placed where the road is quietest"]
        AUDITC["audit_corridors<br/><i>which corridors the chart runs trains through</i>"]
        COST["traffic cost surface<br/>weighted detention + consequence"]
    end

    subgraph MOD["5 · Models — models/"]
        direction LR
        CRIT["<b>criticality.py</b><br/>LightGBM P(fail within H) × Cox urgency × consequence<br/>+ SHAP attribution"]
        DUR["<b>duration.py</b><br/>quantile GBM · P50 reported, <b>P90 reserved</b><br/>conformalised offset"]
        CANC["<b>cancellation.py</b><br/>logistic — weak prior, near the information ceiling"]
    end

    CAND["<b>6 · Candidate enumeration</b> — optimizer/cpsat.py<br/>(section, line, day, start, capacity)<br/>corridor windows + cheapest alternatives<br/><i>premier paths withheld, not priced</i>"]

    subgraph SOLVE["7 · Solve"]
        direction LR
        CPSAT["<b>CP-SAT</b> — weekly, 15-min grid<br/>max Σ crit·done + β·clubbing + corridor − λ·traffic − μ·overdue"]
        MONTH["<b>CP-SAT</b> — monthly, corridor-slot grid<br/>+ extended/mega block demand named"]
        FCFS["<b>baseline.py</b> — first-come-first-served<br/><i>current practice, same hard constraints</i>"]
    end

    EVAL["<b>8 · evaluate.py</b> — KPIs, identical for both plans<br/>risk/block-hour · clubbing · traffic · <b>blocks written to burst</b> · overdue<br/><i>scored against simulator ground truth no model ever sees</i>"]

    SER["<b>9 · serialize.py</b> — the one payload builder"]

    subgraph OUT["10 · Outputs"]
        direction LR
        JSON["out/plan.json"]
        API["scripts/serve.py · FastAPI<br/>/api/plan · /api/resolve · /api/sources"]
        REP["<b>reports.py</b> → scripts/report.py<br/>weekly DRM + monthly GM returns<br/><i>para 3.0 of the 28.12.2016 circular</i>"]
    end

    subgraph GOV["11 · Governance — governance/"]
        direction LR
        WF["workflow.py<br/>JE → dept heads concur → Sr.DOM clears → <b>DRM sanctions</b>"]
        AUD["audit.py<br/>hash-chained, append-only, tamper-evident"]
        IDENT["accounts.py + sessions.py<br/>scrypt passwords, lockout<br/>sessions that expire and can be revoked"]
    end

    WEB["<b>12 · Web</b> — Next.js 16 / React 19<br/>time–distance chart · unified queue · what-if · month view<br/>approvals · audit · data sources"]

    TMS --> LADDER
    SMMS --> LADDER
    TDMS --> LADDER
    LADDER --> NORM --> UTM

    COA --> TT
    TT --> COST
    TT --> AUDITC
    TOPO --> TT
    CORR --> AUDITC
    CORR --> CAND
    TOPO --> CAND

    UTM --> CRIT
    UTM --> DUR
    UTM --> CANC
    COST --> CRIT
    COST --> CAND

    CRIT --> CPSAT
    DUR --> CAND
    DUR --> CPSAT
    CANC --> CPSAT

    CAND --> CPSAT
    CAND --> FCFS
    CAND --> MONTH

    CPSAT --> EVAL
    FCFS --> EVAL
    MONTH --> EVAL
    EVAL --> SER
    AUDITC --> SER

    SER --> JSON
    SER --> API
    JSON --> REP
    JSON --> WEB
    API <--> WEB
    API --> WF
    WF --> AUD
    IDENT --> WF

    PIN["planner pins a block<br/>→ re-solve holding these"]
    WEB -.-> PIN -.-> CPSAT

    classDef src fill:#1f3a5f,stroke:#5b8fd6,color:#eaf1fb
    classDef model fill:#3d2f5c,stroke:#9b7fd4,color:#f0eafb
    classDef solve fill:#14452f,stroke:#4caf7d,color:#e6f6ee
    classDef gov fill:#5c3a1f,stroke:#d69b5b,color:#fbf1ea
    classDef out fill:#1f4f5c,stroke:#5bc6d6,color:#eafafb

    class TMS,SMMS,TDMS,COA src
    class CRIT,DUR,CANC model
    class CPSAT,MONTH,FCFS,CAND solve
    class WF,AUD,IDENT gov
    class JSON,API,REP,WEB out
```

**Three things in that picture are the whole argument.**

*The chainage key at stage 3.* Once an S&T fault at km 412 and an OHE job at km 412.6 are
written in the same coordinates, "are these near each other" becomes arithmetic, and
clubbing becomes something a solver can find.

*The arrow from `duration.py` into candidate enumeration, not just into the objective.* A
task whose P90 plus its withdrawal overruns the corridor is never offered to the solver as
though it fitted. It is named as needing an extended block instead.

*The dotted line back from the web.* A planner drags a block, says "keep that where I put
it and redo the rest", and the solver takes the placement as a hard fact. That is a
different question from the one the original solve answered, and it is the one a human
actually asks.

---

## 2. The approval route

TRACKSEN produces a plan. It never grants a block. `governance/workflow.py` is where that
stops being a sentence in a README and becomes a rule the code enforces — each transition
appended to a hash-chained log, and refused attempts recorded too.

```mermaid
stateDiagram-v2
    direction LR
    [*] --> DRAFT: JE / SSE raises
    DRAFT --> SUBMITTED: submit
    SUBMITTED --> CONCURRED: each dept head concurs<br/>for their own dept only
    CONCURRED --> CLEARED: Sr.DOM clears traffic impact
    CLEARED --> SANCTIONED: DRM sanctions
    SANCTIONED --> [*]

    SUBMITTED --> DRAFT: returned
    CONCURRED --> DRAFT: returned
    CLEARED --> DRAFT: returned

    note right of SANCTIONED
        A sanctioned plan cannot be edited.
        Superseding it means travelling the route again.
    end note

    note left of DRAFT
        Editing a draft invalidates concurrences
        already given: they were granted to a
        different plan.
    end note
```

Only the DRM may sanction; every other role gets a `403`. A department head concurs for
their own department and no other. Sanction requires every department present to have
concurred *and* operations to have cleared — skipping the order gives a `409` listing what
is outstanding. Four rules, all enforced, all tested, and all re-applied as mutants in
`scripts/mutation_check.py` to confirm a test goes red for each.

---

## 3. The ingestion fallback ladder

A design that presumes an API cannot be commissioned. Parts of the estate will give you
nothing but a nightly file, so each source is tried in descending order of fidelity and
falls back — and the run log says which mode answered and why the better ones were skipped.

```mermaid
flowchart LR
    S(["one departmental system"]) --> R{"REST endpoint<br/>configured?"}
    R -- yes --> RO["fetch over REST"]
    R -- no --> D{"read-only DB view<br/>configured?"}
    D -- yes --> DO["open sqlite mode=ro<br/><i>refuses anything but a VIEW</i>"]
    D -- no --> C{"CSV drop<br/>present?"}
    C -- yes --> CO["read nightly file"]
    C -- no --> U["UNAVAILABLE<br/><i>reported, not silently empty</i>"]

    RO --> M["map to Unified Task Model"]
    DO --> M
    CO --> M

    M --> OK["accepted"]
    M --> REJ["rejected <b>by name</b>, with a reason<br/><i>never silently dropped</i>"]

    RO -.-> WHY["each skipped rung is reported<br/>with why it was skipped"]
    DO -.-> WHY
    CO -.-> WHY
```

**Two rules the layer is built on.** Nothing is ever written to a source system — the
SQLite adapter opens `mode=ro` and refuses to run against anything but a view, because a
DBA grants a view rather than a table and the code should make the weaker grant sufficient.
And a record that cannot be mapped is rejected by name, with a reason: silently dropping
malformed rows is how a division discovers six months later that its worst defects were
never scheduled because a date format changed.

The two failures worth testing for here are the ones that *don't* throw. SMMS publishes
chainage in metres — read it as kilometres and every signalling job lands a thousand times
further down the road. SMMS priority P1 is the *most* urgent, the reverse of TMS severity —
map both straight onto an integer and the plan attends the least urgent faults first.
Neither raises an exception. Both are covered by tests and by the mutation check.
