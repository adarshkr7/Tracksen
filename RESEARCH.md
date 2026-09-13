# What Indian Railways actually does, and what TRACKSEN should take from it

Research notes, September 2026. Everything below is sourced; the sources are at the end.
This exists because a judge from the Railway Board will not ask whether the solver is good.
They will ask whether you know what a corridor block is, who signs it, and what the rule says
it should last.

The short version: **the problem statement is not speculative — it is a 2016 Railway Board
instruction that the CAG measured as 2.2% complied with.** TRACKSEN is closer to IR practice
than most SIH entries, but it diverges from the written rule in three places that are cheap to
fix and expensive to be caught on.

---

## 1. The three documents that decide whether judges believe you

### 1.1 The instruction that *is* the problem statement

Railway Board letter **No. 2015/Track-III/TK/5/Pt.I dated 29.12.2016**, "Fixed-Time Integrated
Corridor Blocks for maintenance of assets", reproduces the Minister's own words:

> "Inspection/testing/maintenance of track/signaling/RE assets requires dedicated corridor
> blocks as per world railway practices. Such blocks have to be **Integrated Blocks where all
> departments take advantage of the block**."

Attached to it is a **Joint Circular of AM/Civil Engineering and AM/Traffic**
(No. 2015/Track-III/TK/15, 28.12.2016) which sets the operative rules:

| Para | Rule | TRACKSEN today |
|---|---|---|
| 2.0 | Review the Working Time Table so every section has a planned corridor block of **assured duration — one block of four hours, or two blocks of two-and-a-half hours**. Where margins are inadequate, **reschedule trains** within the zone; if that needs inter-zonal trains, refer to Board. | `CORRIDOR_HOURS = 3` — a single 180-minute window ([network.py:718](samanvay/network.py:718)) |
| 3.0 | A **joint monthly programme** for traffic blocks, issued by COM and PCE, **at least one month in advance**. **Minimum three-hour maintenance blocks, even by regulating Mail/Express or short-terminating passenger trains**, in every section where works are scheduled. | The monthly horizon is exactly this. Train regulation is priced but never *proposed*. |
| 3.0 | **Sr.DOM and Sr.DEN shall make the weekly programme.** Cancellation or reduction of a planned block only **after explicit approval of the DRM**, intimated the previous day. | The weekly horizon, and `governance/workflow.py`, already match this. |
| 3.0 | Cases of cancellation/deviation, **productivity of blocks given**, and **overdue maintenance** go **weekly to the DRM by Sr.DEN/Co-ord and monthly to the GM by PCE**. | These are exactly TRACKSEN's KPIs — but it does not emit them in the mandated shape. |
| 4.0 | DRMs shall ensure full utilisation of blocks planned for integrated maintenance **by Electrical (OHE) and Signal also**. | This is the clubbing bonus, written as a rule. |

So: the monthly plan, the weekly plan, the DRM sanction, the clubbing objective and the overdue
report are not design choices. They are paragraphs 2, 3 and 4 of a circular. **Say so on the
slide.** It converts "we built an optimiser" into "we built the compliance instrument for a
ten-year-old Board instruction".

### 1.2 The audit that says it never happened

CAG (Compliance Report No. 22 of 2021, reworked as an RTI Kolkata case study) measured
compliance directly:

- **"The integrated blocks taken by various departments in 11 Zones in March 2019 was 2.2 per
  cent only. Balance 97.8 per cent of the blocks were availed by departments in isolation."**
- Zonal railways took corridor blocks **longer or shorter than the 240-min / 2×150-min norm**,
  because of late running, new/special trains, and goods trains having no scheduled timing.
- **Trains were scheduled inside the corridor block itself**, so the corridor could not be used.
- **Block bursting**: in six divisions on the NDLS–HWH route in 2018-19, **1,905 cases of block
  bursting delayed 4,659 trains**, with average burst between **38 and 103 minutes**. The stated
  cause is "lack of proper coordination between men, machine and materials."
- Out of 33 punctuality-loss factors in ICMS, **six controllable ones account for 65%** of the
  loss, and two of them are **"Engineering"** and **"Planned block open line"**.
- Delay attributed to engineering asset failure rose from **4.89% (2015-16) to 14.81% (2018-19)**.

That 2.2% is the single most valuable number in this repo's pitch and it is not in the repo.
The baseline TRACKSEN beats is not a straw man — **it is the audited national practice.**

### 1.3 The reform already underway: the Rolling Block Programme

Since 2023 the Board has mandated a **26-week Rolling Block Programme (RBP)**: every division
prepares a block schedule for 26 weeks ahead, per traffic section per line, reviews it weekly,
and adds a 26th week each week. Key details from the IRICEN paper by Sr.DEN/Co/Prayagraj:

- **The system it replaced is the one TRACKSEN's baseline models**: supervisors demanded blocks
  **one day in advance**, divisional control tabulated them, and the Chief Controller allotted
  against whatever margin existed — "lack of coordination between different departments,
  resulting in inefficient use of valuable blocks".
- RBP explicitly requires that **"the requirement of block by different stakeholders shall be
  assessed and dovetailed in a joint manner"**, so that **separate blocks in the same section for
  different departments are avoided** — and that works be planned **"in the shadow of one
  another"**. That phrase is IR's word for clubbing. Use it.
- **Sr.DOM indicates the corridor**, taking account of the integrated corridor block in the WTT,
  historical data and operational patterns. An **empowered committee of branch officers** reviews
  and finalises; **DRM approves**.
- How it is actually run in Prayagraj: **Engineering fills a Google Sheet by 12:00 Thursday**,
  then TRD and S&T fill theirs into the same sheet by evening "so as to utilise the shadow block
  of Engineering"; a TI scrutinises; the empowered committee meets **11:00 Friday**; DRM approves.
- Result: **machine block availability rose from 40–50% to 60–70%** after RBP.
- Blocks planned but not demanded, or not granted, are recorded and reviewed weekly.
- RBP is being written into the **General & Subsidiary Rules** (Board committee, letter
  ERB-12023/23/48 of 25.08.2023) — GR Chapter 15 para 15.02(c), and Operating Manual Ch. 22.

**This is the competitor, and it is a spreadsheet with a Thursday deadline.** TRACKSEN should
position itself as the optimiser inside the RBP process, not as a replacement for anything. And
there is already an official portal — **ROBMS** (`robms.indianrailways.gov.in`) — plus divisional
builds like Southern Railway's RBMS. Know they exist before a judge tells you.

---

## 2. Three changes to make this week

**(a) Corridor length is wrong, and it is costing you 311 tasks.**
`CORRIDOR_HOURS = 3` is the para-3.0 *floor*, not the para-2.0 norm. The norm is **240 minutes,
or two blocks of 150**. The monthly model currently reports "311 tasks cannot fit a corridor at
all — their P90 plus setup and restoration exceeds 180 minutes". A large share of those fit a
240-minute corridor. Make it a flag with the three canonical settings (`--corridor-min 240`,
`--corridor-split 150,150`, `--corridor-min 180`), report the extended-block list against each,
and you get a genuinely new result: *how much of the division's extended-block demand is created
purely by taking a 3-hour corridor instead of the mandated 4*.

**(b) You measure block bursting and never call it that.**
"The duration each department demanded would have contained the actual work 12% of the time" is
the most quotable line in the README. In IR's own vocabulary that sentence reads: **88% of blocks,
as demanded, are written to burst** — and block bursting is a tracked, audited, punctuality-losing
event with a national number attached (1,905 cases → 4,659 trains delayed on one route in one
year). Rename the metric `predicted_burst_rate`, put the CAG number next to yours, and the
duration model stops being a statistics slide and becomes a safety slide.

**(c) Emit the two reports the circular mandates.**
Para 3.0 requires a **weekly return to the DRM** (cancellations, deviations from the agreed block,
**productivity of blocks given**, **overdue maintenance**) and a **monthly return to the GM by the
PCE**. TRACKSEN computes every one of these already — risk retired per block-hour *is* block
productivity, `overdue_task_days` *is* overdue maintenance. Render them as two printable returns
from `serialize.py`. A deliverable that lands in an existing reporting obligation is a deliverable
a division can adopt without asking anyone's permission.

**One more, nearly free:** you hold a 543-service published timetable and the corridor windows.
CAG's finding (ii) was *trains scheduled during the corridor block*. That is a two-line query on
data you already have. Ship it as a Data Sources screen warning — "corridor Danapur–Ara, 10:00–13:00,
is crossed by 4 charted paths" — and you are reproducing a national audit finding on a real
division, automatically. Nobody else at SIH will have that.

---

## 3. The real systems, and which of your mocks they replace

All three of your mock feeds are real CRIS systems. Two more exist that you should name.

| System | Full name | What it actually holds | Role in TRACKSEN |
|---|---|---|---|
| **TMS** | Track Management System (`ircep.gov.in/TMS`) | Track diagram, PSR, **USFD defects**, **TGI from Track Recording Cars**, GMT traffic density, track machine deployment, fracture details | Already your Engineering feed. TGI trend and GMT are the criticality features you don't yet use. |
| **SMMS** | Signalling Maintenance Management System (`smms.indianrailways.gov.in`) | S&T asset register with **geotagged** field data, maintenance schedules, web + mobile for maintainers | Already your S&T feed. The geotag is your chainage key, for free. |
| **TDMS** | Traction Distribution Management System | OHE / traction distribution assets | Already your TRD feed. |
| **TMMS** | **Track Machine Management System** | Machine master, deployment programme, **daily block hours, effective time, output, km** per machine | **Missing.** This is the ground truth for your plant-positioning constraint and your 90-minute buffer. |
| **ROBMS** | **Rolling Block Management System** | The 26-week rolling block programme itself | **Missing.** The system TRACKSEN must sit beside or inside. |
| **ICMS / PAM** | Integrated Coaching Management System, Punctuality Analysis Module | Detention with **cause attribution** across 33 factors, including "Engineering" and "Planned block open line"; pulls timings from COA | **Missing, and it closes your biggest gap.** AUDIT.md says nothing ingests what actually happened. PAM is exactly that feed. |
| **COA / RTIS** | Control Office Application; Real Time Information System | Automatic charting; **loco GPS every 30 seconds** via ISRO GSAT, ~6,500 locos feeding COA directly | Actual path times instead of charted ones; automatic block start/end; drift monitoring. |
| **SATSaNG** | Software Aided Train Scheduling and Network Governance | CRIS's timetabling and path-allocation tool, with delay impact analysis | The system that would have to agree if you propose rescheduling to widen a corridor (para 2.0). |

The IR Track Machines Manual, Chapter 5, is worth reading properly: it sets the **block norms for
machines** (single line: one block of at least 4 hours, or two of 2½, minimum two in exceptional
cases; double line: a 4-hour spell or two 2½-hour split blocks on alternate days), requires the
**deployment programme by 30 September / draft by 31 January / final by 31 March**, and mandates
daily monitoring of **blocks demanded vs blocks given, output, and shortfall reasons**. Your
`--days 7` weekly solve is a sub-problem of a planning cycle that starts eleven months earlier.

---

## 4. Advanced techniques IR is deploying now, and where each plugs in

Ranked by what TRACKSEN could actually use, not by how impressive they sound.

**Wayside condition monitoring → criticality features.** IR runs **24 WILD** (Wheel Impact Load
Detector) and **25 OMRS** (Online Monitoring of Rolling Stock) installations, the latter combining
**RailBAM** acoustic bearing monitoring with wheel condition measurement, plus a **Machine Vision
Inspection System (MVIS)** with DFCCIL that detects hanging or missing components on moving trains.
These are rolling-stock focused, so they are not direct inputs to a *track* block plan — but they
are the template for the argument you are making: IR has already accepted the move **from
time-based to condition-based maintenance**, and TRACKSEN is the scheduling layer that acceptance
implies. Cite them as precedent, not as a data source, or you will be caught.

**Track geometry degradation as a criticality feature.** TMS already carries TGI per section from
Track Recording Cars, and USFD defect records. The mature literature (ANN/SVM/Bayesian models of
TQI degradation, broken-rail prediction on freight railroads) predicts *time to exceedance* from
successive recordings — which is precisely the Cox time-to-failure your criticality model wants,
with a real covariate instead of a synthetic one. This is the highest-value model upgrade
available and it needs no new IR system: TGI trend + GMT + USFD history + last-tamped date.

**Kavach 4.0 as a future constraint source.** ~3,100 route km commissioned by March 2026 with
work in progress on ~24,400 (figures move monthly — check before quoting; recent commissionings
include Manpur–Sarmatanr in **East Central Railway**, your own zone). Kavach's roadmap includes a
**Temporary Speed Restriction Management System** and neutral-section/fouling-mark protection,
and a centralised monitoring platform. What that means for you: the caution orders and TSRs a
block leaves behind — which today are a cost your traffic model ignores — become machine-readable
and enforceable. A block that ends with a 30 km/h TSR for three days is not free, and Kavach is
the system that will eventually price it. Worth one sentence in "future work"; do not claim it.

**RTIS/COA as the execution feedback loop.** This is the concrete fix for the top item in
AUDIT.md. Actual block start and end times, actual detention attributed by PAM, actual overrun —
all exist today in systems with divisional access. Design the adapter (a fourth source in
`ingestion/sources.py`, same ladder, same rejection-by-name discipline) even if you populate it
synthetically. "Here is where the outcome feed lands, and here is the drift monitor it drives" is
a much better answer than "not built yet".

**UIC 406 capacity compression for pricing a window.** Your traffic cost weights detention minutes
against intersecting paths. The international standard method — compress the timetable graph on a
section until buffer times are zero, and read off infrastructure occupation — gives you a
defensible *capacity consumption* number for the section with and without the block, rather than a
weighted count. IR's own capacity studies use simulation tools of this family (RailSys at MRVC;
OpenTrack elsewhere), and the CAG audit specifically criticised IR for **having simulators and not
using them for timetable preparation**. Implementing UIC 406 compression on your existing
543-service timetable is a weekend of work and it answers the sharpest question a traffic officer
can ask: *"how much capacity did this block actually cost me?"*

**The deployment route, if anyone asks how this reaches a division.** The **Rail Tech Policy**,
launched 26 February 2026 with a dedicated portal, invites innovators and startups to submit
technology proposals with **50:50 cost sharing** for prototype development and trials. That is the
answer to "what happens after the hackathon", and it is six months old.

---

## 5. What to say, in one paragraph

Indian Railways decided in December 2016 that maintenance blocks must be integrated across track,
signalling and electrification. In March 2019 the CAG measured integrated blocks at 2.2% of blocks
taken across eleven zones. In 2023 the Board mandated a 26-week Rolling Block Programme to fix it,
and divisions now run that programme on a shared Google Sheet with a Thursday-noon deadline and a
Friday committee. The instruction, the audit and the reform all exist; what is missing is the
thing that turns three departments' demands into one plan — a chainage-keyed model of the estate,
a criticality ranking the three departments can argue with, a duration model that stops blocks
being written to burst, and a solver that finds the shadow work. That is TRACKSEN, and the
competent authority still sanctions it.

---

## Sources

Primary (Indian Railways / statutory):

- [Railway Board, *Fixed-Time Integrated Corridor Blocks for maintenance of assets*, No. 2015/Track-III/TK/5/Pt.I, 29.12.2016, with Joint Circular of AM/CE and AM/Traffic No. 2015/Track-III/TK/15](https://indianrailways.gov.in/railwayboard/uploads/directorate/tracks/Track_3/Corridor_Block_291216.pdf)
- [Indian Railways Track Machines Manual, Ch. 5 — Planning, operation and monitoring of track machines](https://indianrailways.gov.in/railwayboard/uploads/codesmanual/IRTMM-RDSO/TMM_Ch/TMM_Ch_5.html)
- [Track Management System portal](https://ircep.gov.in/TMS/) · [SMMS portal](https://smms.indianrailways.gov.in/) · [ROBMS — Rolling Block Management System](https://robms.indianrailways.gov.in/ROBMS/)
- [CRIS project list — COA, NTES, RTIS, SATSaNG, ICMS, FOIS, SMMS, TMS, TMMS, TDMS, SLAM, e-DRISHTI](https://cris.org.in/loadpage?page=ProjectListPage) · [CRIS/TMS](https://cris.org.in/loadpage?page=proTMS) · [CRIS/ICMS](https://cris.org.in/loadpage?page=proICMS)
- [ICMS Punctuality Analysis Module (PAM) help](https://icms.indianrail.gov.in/icms_help/icms/ICMS/start.htm)

Audit and institutional:

- [CAG / RTI Kolkata, *Case Study on Punctuality and Travel Time in Train Operations in Indian Railways*, July 2023 (based on Compliance Report No. 22 of 2021)](https://cag.gov.in/uploads/research_paper/RES-220900-Peer-Reviewed-Case-Study-on-Punctuality-20230807-052050-1-068f089ca70b4b7-79400532.pdf) — the 2.2% integrated-block figure, block bursting, the 65%/six-factor punctuality analysis
- [CAG, *Compliance Audit on Maintenance of track on heavy traffic sections*, Report No. 45 of 2018](https://cag.gov.in/uploads/download_audit_report/2017/Report_No.45_of_2018_%E2%80%93_Compliance_Audit_on_Maintenance_of_track_on_heavy_traffic_sections_over_India.pdf)
- [S. Prajapati (Sr.DEN/Co, Prayagraj, NCR), *Rolling Block — Paradigm Shift in Inspection and Maintenance of Railway Infrastructure*, IRICEN/IPWE seminar, Nov 2023](https://iricen.gov.in/iricen/ipwe_seminar/2017/Nov%202023%20Vol-1/Rolling%20Block%20-%20Paradigm%205.pdf)
- [S.K. Malik (AMCE/Railway Board), *Track Management System for Indian Railways*](http://www.aitd.net.in/pdf/13/2.%20Management%20Information%20System.pdf)

Current technology:

- [PIB — Kavach 4.0 rollout, 472.3 route km commissioned in a day incl. Manpur–Sarmatanr (ECR)](https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=2221011&reg=3&lang=2) · [DD News — 1,452 km commissioned, safety spending](https://ddnews.gov.in/en/kavach-4-0-commissioned-on-1452-km-of-key-rail-routes-safety-spending-on-indian-railways-triples/) · [IRISET pre-training module on Kavach](https://iriset.railnet.gov.in/content/CoE/docs/English%20Edition%20Pre-Training%20Reading%20Module%20on%20Kavach%20for%20S&T%20staff.pdf)
- [PIB — RTIS: ISRO-developed loco GPS, 30-second mid-section updates into COA](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=1861729)
- [IBEF — WILD (24), OMRS (25), RailBAM, MVIS with DFCCIL](https://www.ibef.org/news/indian-railways-deploys-advanced-ai-machine-learning-devices-to-enhance-safety-and-its-operational-efficiency-by-adopting-smart-monitoring)
- [Metro Rail News — Rail Tech Policy, 26 Feb 2026, 50:50 cost-shared prototypes](https://metrorailnews.in/railway-minister-announces-rail-tech-policy/)
- [NAIR — *Simulation and Potential for Indian Railways* (RailSys at MRVC, OpenTrack)](https://nair.indianrailways.gov.in/uploads/files/1468474436130-Simulation%20-%20Potential%20for%20Indian%20Railways-%20Rajnish%20Kumar.pdf)
- [Liao et al., *Prediction Models for Railway Track Geometry Degradation Using Machine Learning Methods: A Review*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9570632/) · [Machine-learning broken-rail prediction on freight railroads](https://www.sciencedirect.com/science/article/abs/pii/S095006182202013X)

Caveat on figures: Kavach route-kilometre counts and installation counts move month to month and
different official releases disagree. Quote them with their date attached, or not at all.
