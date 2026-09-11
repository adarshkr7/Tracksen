# SAMANVAY — Implementation Deep-Dive Speech

**Length:** ~1,150 words ≈ **6½–7 minutes** at a deliberate technical pace.
**Position:** follows the high-level pitch. Assumes the audience already knows *what* SAMANVAY does.
**To cut to 4 minutes:** drop movement 4 (stability/learning) and compress movement 6 to its last two sentences.
**Delivery cues** are in brackets — strip them before printing.

---

### [Bridge — 0:20]

You've heard what SAMANVAY does. Let me take you underneath it, and show you how it actually works — because the idea is easy to say, and the engineering is where it either holds or falls apart.

### 1. Integration — the unglamorous foundation [→ 1:20]

Start with the least glamorous part, because it is the part that decides whether this system ever runs on a real division.

TMS, SMMS and TDMS were built at different times, by different teams, for different departments. Some expose an API. Some expose only a database. Some will give us nothing but a nightly file. So we don't assume an interface — we write one adapter per source that degrades: REST where it exists, a read-only database view where it doesn't, and a scheduled CSV drop as the floor. Nothing we build reaches into those systems and changes them. They stay the systems of record.

What comes out of every adapter is the same shape — a Unified Task Model. One row per pending job, keyed by section, line, and chainage. **That key is the whole trick.** [*pause*] The moment an S&T fault at kilometre 412 and an OHE job at 412.6 are written in the same coordinates, "are these two jobs near each other" stops being a phone call between two JEs and becomes a spatial query.

That's the foundation. Everything above it depends on it.

### 2. What the models predict [→ 2:50]

On top of that model, four things get predicted.

**First, criticality.** We estimate the probability that an asset fails before its next realistic opportunity for attention — gradient-boosted trees over defect class and severity, asset age, accumulated tonnage, curvature, weld history, days overdue, and how many times that same kilometre has failed before. But probability alone doesn't schedule anything. We need *when*. So we pair it with survival analysis, which gives us a time-to-failure distribution rather than a single number. Then we weight it by consequence — because a defect under a premier path on a busy double line is not the same defect as one on a loop.

**Second, duration.** Departments demand blocks in round figures: two hours, three hours. The actual work almost never takes exactly that. We fit a quantile model and predict both the median and the ninetieth percentile. Then we do something specific — we *reserve* the line against the P90, and we *report* the P50. The plan is honest about the typical case, and the traffic is protected against the bad one.

**Third, traffic cost.** Coaching trains we read straight off the working timetable; they're deterministic. Goods is not — and goods is exactly where the pain is. So we forecast freight path demand per section per hour, and turn it into a cost surface: the price, in paths and detention minutes, of taking this section away at this hour.

**Fourth, cancellation risk.** A block that gets sanctioned and then cancelled has consumed planning capacity and returned nothing. We predict that probability, and we keep a standby queue, so a block released at short notice gets filled instead of lost.

And every one of these carries a SHAP attribution. When the system ranks one task above another, it can say why — overdue by forty-one days, repeat flaw at the same kilometre, premier path density. [*slow down*] That matters more than it sounds. You are asking a divisional officer to defer one department's work in favour of another's. A score he cannot interrogate is a score he will not use.

### 3. The optimiser — where clubbing happens [→ 4:20]

Now the scheduling itself.

We express this in OR-Tools CP-SAT. Every candidate block becomes an interval variable. Each block section becomes a resource under a NoOverlap constraint — that's line exclusivity, enforced structurally rather than by convention. Gangs, tampers and tower wagons become cumulative resources, with positioning time between consecutive sites modelled explicitly, because a tamping machine does not teleport.

The objective has four terms. Add the criticality of every task we complete. Add a bonus for clubbing. Subtract the traffic cost of the window we chose. Subtract a penalty for breaching a statutory schedule.

And clubbing is where the idea earns its name. Because tasks are keyed by chainage, we can ask the solver: are there tasks from *different departments*, within a short span of track, inside a compatible window, whose safety rules allow them to coexist? A disconnection can nest inside a traffic block. Work near the overhead needs a power block anyway. When that pattern appears, the solver is rewarded for collapsing three separate line closures into one.

[*emphasis*] That is not a dashboard telling you something you already knew. It is a constraint model finding combinations across departmental boundaries that no single department could see.

We solve on a rolling horizon — the coming week at fifteen-minute granularity, the next four weeks at corridor-slot granularity, re-solved nightly against what actually happened.

### 4. Stability and the feedback loop [→ 5:00]

One thing we designed deliberately. Each re-solve is warm-started from the plan that was already sanctioned, with a penalty on moving approved blocks. A scheduler that reshuffles the entire week every night is technically optimal and operationally useless. Plans have to be stable enough for people to work against.

And the loop closes. Every block that runs returns its actual start, actual end, and work completed — and that feeds straight back into the duration and cancellation models. The system gets more accurate about that division specifically, the longer it runs there.

### 5. The boundary [→ 5:35]

Now the most important sentence in this presentation. [*pause*]

**SAMANVAY never grants a block.**

It produces a recommended plan. It shows the time–distance chart, the ranked queue, and the reasoning. Departments concur. The competent authority sanctions — exactly as they do today, under the same rules, with the same accountability.

We have deliberately kept the safety-bearing decision where it already sits. Nesting, precedence and regulatory limits are hard constraints, not preferences. A plan the solver cannot make legal, it does not offer.

### 6. Deployment, and one honest note [→ 6:20]

It runs entirely on premises — RailTel or NIC — because operational railway data is not going on a public cloud. The solver is freely licensed, so there is no procurement question sitting between a working prototype and a pilot.

And to be straight with you: we do not have live railway data. What we have is a generator modelled on published maintenance intervals, anchored to one real double-line section, and a first-come-first-served baseline to measure against. Every number we show you is the difference between two runs of the same simulator. On deployment, each synthetic feed is replaced by its adapter — and nothing above that layer changes.

### Close [→ 6:40]

So that's SAMANVAY underneath. One key that puts three departments into the same coordinate system. Four models that say what matters and what it costs. And a solver that finds the coordination no single department could see on its own.

[*slow, land it*] We are not automating the decision. We are making sure the person who makes it can finally see the whole section.
