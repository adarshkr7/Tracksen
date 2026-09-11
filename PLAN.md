> Historical concept/pitch document. Implementation status and current limitations
> are in [STATUS.md](STATUS.md). Any old benchmark numbers or claims of complete
> safety/approval enforcement here are superseded by the code-review fixes.

# SIH 2026 — PS 26027 | AI-Powered Automatic Block Planning
**Ministry of Railways · Software · Transportation & Logistics**

> **Working name: SAMANVAY** (समन्वय — "coordination") — *Unified AI Block Planner for Indian Railways*
> Alternatives: **NIRBAADH** (निर्बाध — "uninterrupted"), **SETU-Block**, **PRAHARI**

**Hard deadline: idea/slide submission — 10 Sep 2026.** Today is 7 Sep. You have ~3 working days.
This document is optimized for that: *win the idea round first, then build*.

---

## 1. What the problem actually is (decoding the PS)

Indian Railways cannot run trains and maintain track on the same line at the same time. So maintenance
happens inside a **block** — a sanctioned window where a block section is taken away from traffic.

Today, three departments each want blocks, independently:

| Dept | System of record | Typical work | Block type |
|---|---|---|---|
| **Engineering (P.Way)** | **TMS** – Track Management System | Rail/weld renewal, tamping, deep screening, USFD-flagged defects, LC gate work | Traffic block (line handed over) |
| **S&T** | **SMMS** – Signalling Maintenance & Management System | Point machine, track circuit, axle counter, IPS, NI work | **Disconnection** (signalling taken out of service) |
| **TRD / Traction Distn.** | **TDMS** – Traction Distribution Mgmt System | OHE mast, contact wire, insulator, isolator, SP/SSP | **Power block** (OHE de-energised) |

- All three raise demands into **BDMS** (Block Demand Management System).
- **COA** (Control Office Application) holds the section's real traffic picture — train running, master
  chart / WTT paths, and the mandated **corridor block** window.
- **Nobody optimizes across the three.** Result: three separate blocks on the same section in one week
  where one clubbed block would do; blocks placed on scarce freight paths; high-criticality defects
  waiting while routine work consumes a corridor; blocks sanctioned but cancelled or under-utilised.

**The gap = coordination + prioritisation + traffic-aware placement.** That is a
*constrained scheduling + risk-ranking* problem. That is the pitch.

### The one-line pitch
> SAMANVAY ingests defect and overdue-maintenance data from TMS, SMMS and TDMS, overlays the train
> timetable and goods forecast from COA, scores every pending task for **failure risk × consequence ×
> urgency**, and solves a **multi-department, multi-section constrained optimisation** to emit a
> ready-to-sanction weekly and monthly block plan into BDMS — with a human always holding the
> sanction pen.

---

## 2. Solution architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  SOURCE SYSTEMS (read-only adapters — no intrusion on legacy systems)         │
│  TMS      SMMS      TDMS      COA (WTT/master chart, train running)     BDMS  │
└────┬────────┬─────────┬──────────────┬──────────────────────────────────┬─────┘
     │ REST / DB view / CSV-SFTP + CDC │                                  │ 2-way
┌────▼────────▼─────────▼──────────────▼──────────────────────────────────▼─────┐
│  L1  INGESTION & NORMALISATION                                                │
│  Adapter per source -> schema mapping -> dedupe -> Unified Task Model (UTM)    │
│  Asset master keyed by (section, line, chainage/km, asset_id)                  │
└──────────────────────────────┬────────────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────────────┐
│  L2  DATA PLATFORM                                                            │
│  PostgreSQL + PostGIS (assets, tasks, blocks) | TimescaleDB (inspection series)│
│  Redis (cache) | MinIO/S3 (attachments, USFD traces)                           │
└──────────────────────────────┬────────────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────────────┐
│  L3  AI/ML SERVICES  (FastAPI microservices, MLflow-tracked)                   │
│  1 Criticality & Failure-Risk Scorer      2 Block Duration Predictor           │
│  3 Traffic-Load / Path-Availability Forecaster   4 Cancellation-Risk Model     │
│  5 SHAP explainer (every score is defensible to a DRM)                         │
└──────────────────────────────┬────────────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────────────┐
│  L4  OPTIMISATION ENGINE                                                      │
│  OR-Tools CP-SAT — multi-objective, rolling horizon                            │
│  Weekly plan @ 15-min granularity | Monthly plan @ corridor-slot granularity   │
│  ALNS/greedy fallback for large instances; warm-start from last week's plan    │
└──────────────────────────────┬────────────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────────────┐
│  L5  APPLICATION — FastAPI + React/TS                                          │
│  Time-distance Gantt · Section map · Clubbing suggestions · What-if simulator   │
│  Role workflow (JE -> Sr.DEN/DSTE/Sr.DEE -> Sr.DOM -> DRM) · Audit trail        │
│  Push sanctioned plan -> BDMS  ·  Deviation feedback loop <- actual outcomes    │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Human-in-the-loop is a feature, not a limitation.** Put this on the slide: the system *recommends*;
the competent authority *sanctions*. Safety-critical authority never moves to an algorithm. Railway
judges will penalise anything that sounds like it auto-grants blocks.

---

## 3. The AI/ML layer — be specific, not buzzwordy

### 1. Criticality & Failure-Risk Score → `P(failure before next opportunity) × Consequence`
- **Model:** gradient boosting (XGBoost/LightGBM) for risk probability + **survival analysis**
  (Cox PH / Random Survival Forest) for *time-to-failure*, which is what actually drives scheduling.
- **Features:** defect class & severity (e.g. USFD flaw classification), asset age, GMT / traffic
  density, curvature & gradient, weld/joint history, last attention date, days overdue vs schedule,
  repeat-failure count at that km, rainfall/temperature regime, monsoon/fog season flag.
- **Consequence weight:** train density on that line, route classification, presence of premier paths
  (Rajdhani / Vande Bharat / mail), whether failure causes a **line block vs a speed restriction**, and
  whether it triggers an imposed **TSR/PSR**.
- **Output:** a 0–100 **Criticality Index** with SHAP reasons
  ("+22 overdue by 41 d, +18 repeat flaw at km 412/3, +11 premier path density").

### 2. Block Duration Predictor
Departments habitually demand round numbers (2 h, 3 h) while actuals differ — the single biggest source
of block over-run and cancelled paths. Quantile GBM on historical block records (work type, quantity,
gang strength, machine type — tamper / UTV / BCM / tower wagon, site access, night vs day, monsoon)
predicting **P50 and P90**. **Schedule against P90, report P50.** This is a genuinely expert-sounding
detail and costs you nothing.

### 3. Traffic-Load / Path-Availability Forecaster
- Coaching trains are deterministic (WTT). **Goods is not** — that's where the value is.
- Time-series model (SARIMAX/Prophet baseline → LightGBM with calendar features) forecasting freight
  path demand per section per hour, plus seasonal loads (rake cycles, festival specials).
- Output: an hourly **traffic cost surface** per section — the price of taking the line away at hour *h*.

### 4. Cancellation-Risk Model
Predicts the probability a demanded block gets cancelled or curtailed (late running, machine
non-availability, staff, weather). Used to (a) avoid planning against fragile slots and (b) maintain a
**standby task queue** so a released block is never wasted.

### 5. Optimisation formulation (a compact version of this goes on the Technical Approach slide)

**Decision:** `x[t, s, w] ∈ {0,1}` — task *t* scheduled in block section *s*, in time window *w*.

**Maximise**
```
  Σ_t  Criticality(t) · Completed(t)          <- risk retired / availability gained
+ β ·  Σ_b ClubbingBonus(b)                   <- multi-dept work sharing one block
- λ ·  Σ_w TrafficCost(s, w)                  <- paths lost, detention minutes
- μ ·  Σ_t OverdueBreach(t)                   <- statutory schedule violation
```

**Subject to**
1. **Line exclusivity** — no overlapping blocks on the same block section/line unless declared compatible.
2. **Precedence & nesting** — S&T disconnection nested inside the traffic block; OHE power block required
   for any work in OHE proximity; NI work sequencing.
3. **Corridor policy** — respect the pre-defined maintenance corridor in the master chart; blocks outside
   it need justification and carry a higher traffic cost.
4. **Resources** — gangs, PWI/JE availability, machines (tamper, BCM, UTV, tower wagon) with positioning
   / travel time between consecutive sites; ART/ARME availability.
5. **Duration** — predicted P90 duration fits inside the window; minimum gap between successive blocks.
6. **Regulatory / safety** — max block duration, night-work restrictions, declared fog/monsoon
   restrictions, VIP and special movements, festival-rush embargo.
7. **Statutory schedule** — periodic maintenance (tamping, USFD, OHE inspection) within due date + tolerance.

**Solver:** OR-Tools **CP-SAT** with interval variables, `NoOverlap` on section resources, cumulative
constraints on gangs/machines. Rolling horizon: week *W* at 15-min granularity, weeks *W+1..W+4* at
coarse corridor slots, re-solved nightly with actuals. Warm-start from the previous solution so the plan
is **stable** — planners hate a schedule that reshuffles wholesale every night. Say that out loud.

**Reality check:** don't claim RL. Put "RL for adaptive re-planning under live disruption" in **future
scope**. CP-SAT + supervised ML is the defensible, buildable answer.

---

## 4. Product surface — what the judges will actually see

1. **Time–distance block chart** (the money shot). X = time, Y = km / stations along the section. Train
   paths as diagonal lines, proposed blocks as shaded rectangles, corridor window shaded green. This is
   the artefact every railway officer reads daily — showing it signals domain fluency instantly.
2. **Unified priority queue** — pending tasks across all three departments in one ranked list,
   colour-coded by department, each row carrying a SHAP "why" chip.
3. **Clubbing suggestions** — "3 demands on SEC-04 within 6 days → 1 combined block, saves 2 paths."
   This card *is* the PS's core ask. Make it visually loud.
4. **What-if simulator** — drag a block to a new slot → instant recompute of trains affected, detention
   minutes, and risk carried forward. Interactive = memorable in a 6-minute demo.
5. **Monthly corridor view** — heatmap of section × day, planned block load vs asset-risk backlog.
6. **KPI header** — Asset Availability %, Block Utilisation %, Overdue Backlog, Detention Minutes,
   Cancellation Rate (definitions in §7).
7. **Approval workflow** — plan → dept heads concur → Sr.DOM / DRM sanction → push to BDMS, with audit trail.

---

## 5. Tech stack (pick this and stop debating)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.11 + FastAPI** | Same language as ML and solver; fastest to demo |
| Optimiser | **OR-Tools CP-SAT** | Free, industrial-grade, handles this scale, no licence question |
| ML | scikit-learn, LightGBM/XGBoost, lifelines (survival), SHAP | Explainability out of the box |
| Forecasting | statsmodels / Prophet baseline + LightGBM | Sufficient for goods-path forecasting |
| DB | **PostgreSQL 16 + PostGIS**, TimescaleDB, Redis | Geospatial chainage + time-series in one stack |
| Frontend | **React + TypeScript + Vite**, Tailwind, **D3** (time-distance chart), Leaflet (map) | Nothing off-the-shelf draws a train graph — D3 it is |
| Auth | Keycloak / LDAP hook, RBAC by department & designation | Matches IR's existing directory |
| Deploy | Docker Compose (demo) → **Kubernetes on RailTel / NIC cloud**, fully on-prem capable | Data sovereignty; IR won't put ops data on public cloud |
| Ops | MLflow, Prometheus + Grafana, structured audit log | Model-governance story for the viva |

**Integration reality:** legacy systems may not expose APIs. Design each adapter to work three ways —
REST if available, read-only DB view / materialised view if not, scheduled SFTP CSV as the floor. Say
this explicitly on the feasibility slide; it shows you've thought about real deployment.

---

## 6. Data strategy (you have no real IR data — handle it head-on)

- **Public / real where possible:** train timetable (public IR timetable dumps), station and section
  codes, route maps, the Railway Board corridor-block policy, IRPWM periodic-maintenance intervals.
- **Synthetic-but-faithful for the rest:** a `data_generator.py` producing TMS/SMMS/TDMS-shaped records
  with realistic distributions — defect arrival as a Poisson process modulated by GMT and monsoon, USFD
  flaw classes, OHE fault types, point-machine failure rates, block demands, and *actual vs demanded*
  durations with realistic over-run.
- **Anchor it to one real section** for the demo (a double-line electrified section of ~120 km,
  8–10 stations). Naming a real division/section makes the slide concrete. Keep the disclaimer:
  *"Synthetic data statistically modelled on published IR maintenance schedules; plugs into live
  TMS/SMMS/TDMS via adapters on deployment."*
- **Never claim you have real IR operational data.** Judges will ask. The honest answer is the strong one.

---

## 7. KPI definitions (use these exact ones — they make the impact slide credible)

| KPI | Definition |
|---|---|
| **Asset Availability %** | Time asset is fit for design speed ÷ total time, across the section |
| **Block Utilisation %** | Actual productive work minutes ÷ block minutes sanctioned |
| **Corridor Adherence %** | Blocks taken inside the mandated corridor ÷ total blocks |
| **Clubbing Ratio** | Multi-department tasks per sanctioned block (target > 1.0) |
| **Overdue Backlog** | Count and age-weighted sum of tasks past statutory due date |
| **Traffic Cost** | Detention minutes + paths lost, per block |
| **Cancellation Rate** | Blocks cancelled or curtailed ÷ blocks sanctioned |
| **Risk Retired per Block-Hour** | Σ criticality of tasks completed ÷ block hours consumed — *headline metric* |

**On impact numbers:** present them as **modelled results from your own simulation**, with the
assumption stated next to the number, e.g. *"On a 120 km simulated section over 30 days, SAMANVAY raised
risk-retired-per-block-hour by X% and cut sanctioned-but-idle block time by Y% versus a
first-come-first-served baseline."* Run the baseline, measure, quote your number. Do **not** invent a
national "₹__ crore saved" figure — an IR officer will take it apart in the viva.

---

## 8. Demo scope fence (what to build, what to defer)

**In scope for the prototype:**
- 1 division, 3–4 block sections, 3 departments, ~200 pending tasks, 30-day horizon
- Criticality scorer + duration predictor trained on synthetic history
- CP-SAT weekly optimiser + monthly coarse plan
- Time-distance chart, priority queue, clubbing card, what-if simulator, KPI header
- **Baseline-vs-optimised comparison screen** — this *is* the proof

**Explicitly future scope (saying so reads as maturity, not weakness):**
- RL-based re-planning under live disruption
- IoT / sensor-fed condition monitoring (track-geometry cars, OHE sensors)
- Real-time integration with the live COA train-running feed
- Multi-division / zonal rollout with resource pooling
- Certified BDMS write-back and safety-audit sign-off

---

## 9. Three-day sprint to 10 Sep

### Day 0 — tonight, 7 Sep (2–3 h)
- [ ] Lock the name, the one-line pitch, and three headline claims
- [ ] Assign roles: **Slides + story (1)**, **Backend/optimiser (2)**, **ML (1)**, **Frontend (1)**, **Domain research (1)**
- [ ] Pick the real section for the demo; collect its station list and a few train timings
- [ ] Skim: Railway Board corridor-block policy, IRPWM maintenance-schedule chapter, any TMS/BDMS user
      manual. Harvest **vocabulary** — the slides must sound like Railways, not like a generic
      scheduling startup.

### Day 1 — 8 Sep
- **Tech:** synthetic data generator → criticality scorer v1 → CP-SAT model v1 producing *any* feasible
  weekly plan → React skeleton with a static time-distance chart.
- **Slides:** full text draft of all five content slides; architecture diagram v1 (draw.io / Excalidraw).
- **Gate:** the solver emits a plan and you can screenshot something.

### Day 2 — 9 Sep
- **Tech:** baseline (FCFS) vs optimised comparison with real KPI numbers; clubbing logic; make the chart
  real; screenshot-quality polish on *one* screen only.
- **Slides:** drop in real screenshots and your measured numbers; finish all diagrams; internal review;
  cut every sentence that isn't railway-specific.
- **Record a 60–90 s screen capture** of the flow — useful in the finals, and one frame makes a great slide visual.

### Day 3 — 10 Sep
- Morning: final polish, proofread, confirm the official SIH template hasn't changed, export to **PDF**.
- **Submit by early afternoon.** The portal reliably jams on the last evening. Don't be the team
  refreshing at 11:47 pm.

---

## 10. Slide pack

Official template: `SIH2026-IDEA-Presentation-Format.pptx` (13.33″ × 7.5″). Its own rules:
**max 6 slides including the title**, no paragraphs, keep the idea-details pointer lines, delete the
instructions slide, **upload as PDF only**.

Slide-by-slide layout maps, word budgets and paste-ready copy: [SLIDES.md](SLIDES.md).

---

## 11. What wins this round — and the traps

**Win:**
- Speak Railways: *block section, corridor block, disconnection, power block, master chart, WTT, path,
  detention, TSR/PSR, NI work, sanction, PWI/JE, Sr.DEN/DSTE/Sr.DEE, Sr.DOM, DRM.*
- Show the **time–distance chart**. Nothing says "we understand block planning" faster.
- Lead with **clubbing across departments** — the PS's actual pain, and visually obvious.
- Quantify from your **own simulation**, with the assumption written beside the number.
- State human-in-the-loop sanction authority explicitly.

**Traps:**
- Claiming autonomous block granting → instant credibility loss on safety grounds.
- "We'll use deep learning / RL / LLMs" with no formulation → judges probe, it collapses.
- Generic dashboard screenshots with no train graph.
- Fabricated crore-value savings.
- Ignoring that TMS/SMMS/TDMS may have no APIs — always mention the adapter fallback.

---

## 12. Repo layout to start with

```
SIH/
├─ PLAN.md                 <- this file
├─ SLIDES.md               <- paste-ready slide copy
├─ docs/
│  ├─ architecture.drawio
│  ├─ domain-notes.md      <- vocabulary + policy references as you find them
│  └─ kpi-definitions.md
├─ data/
│  ├─ generator.py         <- synthetic TMS/SMMS/TDMS/COA feeds
│  └─ seed/                <- section master, station list, WTT extract
├─ services/
│  ├─ ingestion/           <- adapters + Unified Task Model
│  ├─ ml/                  <- criticality, duration, traffic forecast, SHAP
│  ├─ optimizer/           <- CP-SAT model, objective weights, baseline FCFS
│  └─ api/                 <- FastAPI
├─ web/                    <- React + TS + D3 time-distance chart
└─ eval/
   └─ baseline_vs_optimized.py   <- produces the numbers for the impact slide
```

---

## 13. Open decisions to close today
1. Which real section / division anchors the demo?
2. Objective weights (β clubbing, λ traffic, μ overdue) — expose them as **planner-tunable sliders** in
   the UI; that turns a modelling weakness into a feature.
3. Who owns the deck end-to-end? (One person. Committee-written decks lose.)
4. Does anyone on the team have a railway contact — a relative or alum in IR? A 20-minute call for
   vocabulary and workflow validation is worth more than a full day of coding.
