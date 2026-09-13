# SLIDES.md — deck spec against the official SIH 2026 template
**PS 26027 · AI-Powered Automatic Block Planning · Ministry of Railways**
Template: `SIH2026-IDEA-Presentation-Format.pptx` (13.33″ × 7.5″, 16:9)

---

## Hard rules from the template's own instruction slide

| Rule | Consequence for us |
|---|---|
| **Max 6 slides, including the title slide** | Title + Idea + Technical + Feasibility + Impact + References = exactly 6. Zero spare slides. |
| **Avoid paragraphs — points / diagrams / infographics / pictures** | Every slide is bullets + one visual. No prose blocks. |
| **Use the provided template without changing the idea-details pointers** | Keep the prompt lines ("Detailed explanation of the proposed solution", etc.) present on each slide. Resize/reposition boxes and add content around them — but don't delete the pointers. |
| **Save as PDF and upload — no PPT/DOC accepted** | Final export is PDF. Check fonts survive the export. |
| **Delete the instructions slide (7) before upload** | Do this last, and re-check the slide count is 6. |

**Also on every content slide:** replace the "Your Team Name" oval at top-left (x 0.36, y 0.28) with your
actual team name. It's easy to miss on five slides.

---

## Canvas map (identical on slides 2–6)

```
x=0                                                              x=13.33
 ┌──────────────────────────────────────────────────────────────────┐ y=0
 │ (oval) Your Team Name        TITLE (y 0 → 1.25)      [SIH logo]  │
 │  0.36,0.28  1.37×0.88                          10.70,0 2.46×1.16 │ y=1.25
 ├──────────────────────────────────────────────────────────────────┤
 │                                                                  │
 │        USABLE CONTENT AREA                                       │
 │        x 0.40 → 12.90   (12.5″ wide)                             │
 │        y 1.35 → 6.85    (5.5″ tall)                              │
 │                                                                  │
 │   Default pointer TextBox ships at y=2.77, w=10.26, h≈1.5–2.0    │
 │   → shrink it to a caption strip, reclaim the rest               │
 │                                                                  │
 ├──────────────────────────────────────────────────────────────────┤ y=6.95
 │ footer bar: @SIH Idea submission- Template          slide no.    │
 └──────────────────────────────────────────────────────────────────┘ y=7.5
```

**Blocked zones:** top-right 2.5″ (SIH logo), top-left 1.4″ (team oval), bottom 0.55″ (footer bar).
**Recommended split:** text column `x 0.4 → 6.6`, visual `x 6.9 → 12.9`. Both `y 1.5 → 6.8`.

**Word budget: ~85–95 words of body text per slide.** More than that at 14 pt in a 6″ column overflows
or forces unreadable type. The copy below is already cut to fit — resist re-padding it.

---

## SLIDE 1 — TITLE PAGE

Fill the left TextBox (x 0.36, y 2.27, 6.48″ × 5.14″). Right half is template artwork — leave it.

```
Problem Statement ID    : 26027
Problem Statement Title : AI-Powered Automatic Block Planning to Maximize Asset
                          Availability for Train Operations on Indian Railways
Theme                   : Transportation & Logistics
PS Category             : Software
Team ID                 : <your team ID>
Team Name               : <exactly as registered on the portal>
```

Copy the PS title character-for-character from the portal. A mismatch here looks careless before anyone
reads slide 2.

---

## SLIDE 2 — IDEA TITLE (Proposed Solution)

**Idea title line (put it directly under the "IDEA TITLE" heading, 20–24 pt bold):**
> **TRACKSEN — one AI-optimised block plan for three departments**

**Left column (text, x 0.4 → 6.6) — keep the three pointer labels as bold mini-headers:**

**Detailed explanation**
- Unifies **TMS** (P.Way), **SMMS** (S&T), **TDMS** (OHE) demands with **COA** train paths, goods forecast and corridor windows
- AI scores every pending task — failure risk × consequence × days overdue → **Criticality Index**, SHAP-explained
- **OR-Tools CP-SAT** places blocks; weekly (15-min) + monthly plans pushed to **BDMS** for sanction

**How it addresses the problem**
- Replaces 3 independent first-come-first-served queues with **1 coordinated, traffic-aware plan**
- **Clubs** Engineering + S&T + TRD work into a single line closure

**Innovation & uniqueness**
- Objective = **risk retired per block-hour**, not tasks completed
- **Predicted P90 duration** replaces the demanded round figure
- Explainable scores; **sanction authority stays with the officer**

*(≈ 95 words — trim the last innovation bullet if it runs long.)*

**Right column visual — "Before vs After" strip.** Two mini time–distance bands for the same section
and week: *Before* = three separate blocks scattered outside the corridor; *After* = one clubbed block
inside the green corridor window. This single graphic carries the whole idea.

---

## SLIDE 3 — TECHNICAL APPROACH

**Left column (text):**

**Technologies**
- **AI/ML:** LightGBM/XGBoost (criticality), survival analysis (time-to-failure), quantile GBM (P50/P90 block duration), SARIMAX + LightGBM (goods path forecast), SHAP
- **Optimisation:** Google **OR-Tools CP-SAT** — interval vars, NoOverlap per section, cumulative gang/machine limits
- **Stack:** Python · FastAPI · PostgreSQL + PostGIS · React + TypeScript + D3
- **Deployment:** Docker + Kubernetes on **RailTel / NIC on-prem**; RBAC via IR LDAP
- **Integration:** adapter per source — REST → read-only DB view → SFTP CSV

**Methodology**
`Ingest → Normalise (Unified Task Model) → Score → Optimise → Review & Sanction → Push to BDMS → Learn from actuals`

*(≈ 90 words.)*

**Right column visual — the layered architecture diagram** (L1–L5 from `PLAN.md` §2), with the
objective function on one line beneath it:

> `max  Σ Criticality·Done  +  β·Clubbing  −  λ·TrafficCost  −  μ·OverdueBreach`

That one line does more for credibility than any amount of prose. Keep it legible — 12 pt minimum.

---

## SLIDE 4 — FEASIBILITY AND VIABILITY

**Left column (text):**

**Feasibility**
- **No new hardware** — consumes data TMS, SMMS, TDMS, COA and BDMS already hold
- Division-scale instance (4 sections, ~200 tasks, 30 days) solves in **seconds** on commodity hardware
- Sits **alongside BDMS** as decision support — statutory sanction process unchanged, so no safety re-certification to start
- Fully **on-prem**; no data leaves IR

**Adoption:** pilot one division → measure vs FCFS baseline → publish KPI delta → extend across the zone.

*(≈ 70 words — leaves room for the table.)*

**Right column visual — risks table (3 columns wide, 12 pt):**

| Risk | Mitigation |
|---|---|
| Legacy systems without APIs | 3-tier adapter: REST → DB view → SFTP CSV |
| Incomplete defect records | Confidence-weighted scoring; low-confidence tasks flagged for manual review |
| Departmental trust | Explainable scores, tunable weights, advisory-only output |
| Plan churn on re-solve | Warm-start + stability penalty on approved blocks |
| Live disruptions | Nightly re-solve + standby queue fills released blocks |
| Safety of disconnections | Hard nesting/precedence constraints; officer sanctions |

Six rows is the maximum that stays readable. Drop the bottom two if the type gets small.

---

## SLIDE 5 — IMPACT AND BENEFITS

**Top strip — three big stat callouts (48–60 pt numbers, 11 pt labels):**

```
   +X%                    −Y%                     −Z%
risk retired per      sanctioned-but-idle      overdue defect
   block-hour            block time               backlog
```

> Replace X/Y/Z with numbers `eval/baseline_vs_optimized.py` actually produces. Put the assumption in
> 10 pt directly under the strip: *"Simulated: 120 km double-line section, 30 days, vs first-come-first-served baseline."*
> Do **not** invent a national ₹-crore figure — an IR officer will take it apart in the viva.

**Left column (text):**

**Impact on target audience**
- **Divisional planners:** one ranked, cross-department queue instead of three
- **Operations:** blocks land in the cheapest traffic window — fewer paths lost, less detention
- **Asset holders:** critical defects attended *before* failure, not after

**Benefits**
- **Safety:** risk-ranked attention; auditable record of what was deferred and why
- **Economic:** freight paths and punctuality preserved — the real cost of a bad block is detention minutes
- **Institutional:** repeatable, auditable process that survives officer transfers
- **Environmental:** fewer unplanned halts and speed restrictions → less idling and braking-cycle fuel burn

*(≈ 90 words including the stat labels.)*

**Right column visual — baseline vs TRACKSEN KPI bars** (4 bars, paired), or a screenshot of the
time–distance chart if the UI is ready by the 9th. Prefer the screenshot — it proves you built something.

---

## SLIDE 6 — RESEARCH AND REFERENCES

Keep it to **6–8 real, verified links**, grouped. Two columns, 11–12 pt.

**Domain & policy**
- Railway Board circular on pre-defined **corridor blocks** in the master chart
- **IRPWM** — periodic maintenance schedules, USFD, tamping intervals
- **IRSEM** — disconnection procedure · **ACTM** — OHE power block procedure
- CRIS public documentation for **TMS / COA / BDMS**

**Technical**
- Google **OR-Tools CP-SAT** scheduling documentation
- 1–2 peer-reviewed papers on railway possession / maintenance-window scheduling
  (search: *"railway possession scheduling optimisation"*, *"track maintenance scheduling MILP"*)
- SHAP — explainable ML for operational decision support

**Data**
- Indian Railways Annual Statistical Statements (for any failure/punctuality figure you cite)

> Open every link before submission. A dead or invented reference does more damage than a short list.

---

## Pre-submission checklist — 10 Sep, morning

**Template compliance**
- [ ] Exactly **6 slides**; instructions slide (7) deleted
- [ ] All five pointer lines still present on their slides (not deleted)
- [ ] "Your Team Name" oval replaced on **all five** content slides
- [ ] Footer bar and slide numbers intact

**Content**
- [ ] PS ID **26027**, PS title copied verbatim from the portal, theme = Transportation & Logistics, category = Software, team ID + registered team name correct
- [ ] Every slide ≤ ~95 words; no paragraphs anywhere
- [ ] Every slide has one visual
- [ ] X/Y/Z placeholders replaced with measured numbers, assumption line present
- [ ] No claim of autonomous block granting anywhere in the deck
- [ ] Every reference link opens

**Export**
- [ ] Nothing overflows its box at 100% zoom — check after the PDF export, not before
- [ ] Exported as **PDF**, within the portal's size limit
- [ ] **Uploaded by early afternoon** — the portal jams on the final evening
