# -*- coding: utf-8 -*-
"""Fill the official SIH 2026 idea template for TRACKSEN (PS 26027) and export the PDF.

    python scripts/build_idea_deck.py --template SIH2026-IDEA-Presentation-Format.pptx \
        --team-name "..." --team-id "..." --shots <dir> --pdf

The template is filled in, not redesigned. Slide 1 only has its blanks completed, in the
template's own runs. On slides 2-6 the title, team oval, SIH logo, footer and every
idea-details pointer keep their wording, typeface, colour and bullets; the answers are
written beneath each pointer, and a visual sits beside them. The instructions slide is
removed, as the template itself says to.

`--shots` is a directory holding planning.png and intelligence.png: 2400x1500 captures of
the web app's /planning and /intelligence pages (1600x1000 at device scale 1.5).
"""
from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.oxml import parse_xml
from pptx.util import Inches, Pt

# The template's own palette: dk2 navy, the footer-bar blue, accent2 red.
NAVY = "1F497D"
BLUE = "0070C0"
RED = "C0504D"
GREEN = "4E7D2A"
INK = "262626"
GREY = "595959"
PALE = "F2F6FB"
PALE_RED = "FBEDEC"
PALE_GREEN = "EEF5E8"
RULE = "C9D5E6"
WHITE = "FFFFFF"
FONT = "Arial"

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

PS_TITLE = ("AI-Powered Automatic Block Planning to Maximize Asset Availability "
            "for Train Operations on Indian Railways")
IDEA_TITLE = "AI-Optimised Integrated Block Planning to Maximise Line and Asset Availability"

# Right-hand visual column, shared by slides 2-5.
RX, RW = 7.02, 5.91
TOP, BOTTOM = 1.30, 6.84


def emu(inches: float) -> int:
    return int(round(inches * 914400))


def rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


# ------------------------------------------------------------------ text primitives
def B(text: str, color: str = NAVY) -> tuple[str, dict]:
    return text, {"bold": True, "color": color}


def par(parts, size=11.0, marL=0.50, indent=-0.17, bullet="▪", bcolor=BLUE,
        before=2.5, line=None, align="l"):
    """A new <a:p>. `parts` are plain strings (ink) or (text, style) pairs from B()."""
    p = etree.Element(A + "p", nsmap={"a": A[1:-1]})
    pPr = etree.SubElement(p, A + "pPr", marL=str(emu(marL)), indent=str(emu(indent)),
                           algn=align)
    if line:
        ln = etree.SubElement(pPr, A + "lnSpc")
        etree.SubElement(ln, A + "spcPct", val=str(int(line * 100000)))
    sb = etree.SubElement(pPr, A + "spcBef")
    etree.SubElement(sb, A + "spcPts", val=str(int(before * 100)))
    if bullet:
        c = etree.SubElement(pPr, A + "buClr")
        etree.SubElement(c, A + "srgbClr", val=bcolor)
        etree.SubElement(pPr, A + "buFont", typeface=FONT)
        etree.SubElement(pPr, A + "buChar", char=bullet)
    else:
        etree.SubElement(pPr, A + "buNone")
    for part in parts:
        text, style = (part, {}) if isinstance(part, str) else part
        r = etree.SubElement(p, A + "r")
        rPr = etree.SubElement(r, A + "rPr", lang="en-US", sz=str(int(style.get("size", size) * 100)),
                               b="1" if style.get("bold") else "0", dirty="0")
        if style.get("italic"):
            rPr.set("i", "1")
        fill = etree.SubElement(rPr, A + "solidFill")
        etree.SubElement(fill, A + "srgbClr", val=style.get("color", INK))
        etree.SubElement(rPr, A + "latin", typeface=style.get("font", FONT))
        etree.SubElement(rPr, A + "cs", typeface=style.get("font", FONT))
        etree.SubElement(r, A + "t").text = text
    return parse_xml(etree.tostring(p))     # as python-pptx's own element classes


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    return tf


def write(tf, paragraphs):
    """Replace a text frame's content with the given <a:p> elements."""
    body = tf._txBody
    for p in body.findall(A + "p"):
        body.remove(p)
    for p in paragraphs:
        body.append(p)


def label(slide, x, y, w, h, parts, size=10.0, align="l", anchor=MSO_ANCHOR.MIDDLE, line=None):
    tf = textbox(slide, x, y, w, h, anchor)
    write(tf, [par(parts, size=size, marL=0, indent=0, bullet=None, before=0, align=align,
                   line=line)])
    return tf


def box(slide, x, y, w, h, fill=None, line=None, lw=0.75, shape=MSO_SHAPE.RECTANGLE, radius=None):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius is not None:
        sh.adjustments[0] = radius
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    if line:
        sh.line.color.rgb = rgb(line)
        sh.line.width = Pt(lw)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


# ------------------------------------------------------------------ template elements
def shape(slide, name_prefix):
    for sh in slide.shapes:
        if sh.name.startswith(name_prefix):
            return sh
    raise KeyError(name_prefix)


def set_run_text(run_elm, text):
    run_elm.find(A + "t").text = text


def fill_team_oval(slide, team_name):
    """Only the words change; the oval keeps its size, outline and font. An ellipse's text
    area is narrower than the oval, so a one-word name wraps mid-word unless wrapping is
    off -- with it off the name stays centred and still sits inside the outline."""
    oval = shape(slide, "Oval")
    oval.text_frame.word_wrap = False
    runs = oval.text_frame.paragraphs[0].runs
    runs[0].text = team_name
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def pointers(slide, x, y, w, size=14.0, heading_size=None):
    """Move the pointer box into the text column and scale its type to leave room for the
    answers. Wording, bullets, typeface, colour and underline are the template's."""
    sh = shape(slide, "TextBox 8")
    sh.left, sh.top, sh.width = Inches(x), Inches(y), Inches(w)
    body = sh.text_frame._txBody
    kept = []
    for p in body.findall(A + "p"):
        if not "".join(t.text or "" for t in p.iter(A + "t")).strip():
            body.remove(p)          # blank spacer lines only; every pointer stays
            continue
        is_heading = p.find(f"{A}pPr/{A}buFont[@typeface='Wingdings']") is not None
        sz = str(int((heading_size if is_heading and heading_size else size) * 100))
        for rpr in p.iter(A + "rPr", A + "endParaRPr"):
            rpr.set("sz", sz)
        pPr = p.find(A + "pPr")
        sb = pPr.find(A + "spcBef")
        if sb is None:                  # schema order: lnSpc, then spcBef
            sb = etree.Element(A + "spcBef")
            ln = pPr.find(A + "lnSpc")
            pPr.insert(0 if ln is None else list(pPr).index(ln) + 1, sb)
        for child in list(sb):
            sb.remove(child)
        etree.SubElement(sb, A + "spcPts", val="700" if kept else "0")
        kept.append(p)
    return kept


def answer(pointer_p, paragraphs):
    anchor = pointer_p
    for p in paragraphs:
        anchor.addnext(p)
        anchor = p


# ------------------------------------------------------------------ slide 1
def fill_title_slide(slide, team_id, team_name):
    """Complete the blanks. The six labels keep their 24pt bold Arial and their bullets;
    each value is a copy of its label's run in regular weight.

    At the template's double line spacing the six labels alone fill the box, so two things
    give: spacing drops to 150%, and the two values too long to share a line with their
    label (the PS title, the team name) go on the line beneath it."""
    tb = shape(slide, "TextBox 9")
    paras = [p for p in tb.text_frame.paragraphs if p.text.strip()]
    rows = [                     # (label rewrite, value, size, own line)
        (None, " 26027", 20, False),
        (None, PS_TITLE, 16, True),
        (None, " Transportation & Logistics", 20, False),
        ("PS Category- ", "Software", 20, False),
        (None, " " + team_id, 20, False),
        (None, team_name, 20, True),
    ]

    def value_run(label_run, text, size):
        v = copy.deepcopy(label_run)
        set_run_text(v, text)
        rPr = v.find(A + "rPr")
        rPr.set("b", "0")
        rPr.set("sz", str(size * 100))
        return v

    for p, (label_text, value, size, own_line) in zip(paras, rows):
        p._p.find(f"{A}pPr/{A}lnSpc/{A}spcPct").set("val", "150000")
        r0 = p.runs[0]._r
        if label_text is not None:
            set_run_text(r0, label_text)
        if not own_line:
            r0.addnext(value_run(r0, value, size))
            continue
        q = copy.deepcopy(p._p)          # same paragraph style, minus the bullet
        for r in q.findall(A + "r"):
            q.remove(r)
        pPr = q.find(A + "pPr")
        pPr.set("indent", "0")
        pPr.set("algn", "l")
        for tag in ("buFont", "buChar"):
            pPr.remove(pPr.find(A + tag))
        etree.SubElement(pPr, A + "buNone")
        pPr.find(f"{A}lnSpc/{A}spcPct").set("val", "115000")
        q.insert(1, value_run(r0, value, size))
        p._p.addnext(q)


# ------------------------------------------------------------------ slide 2
def slide_idea(s, team):
    # The placeholder reads "IDEA TITLE" after a blank run and a line break; only that
    # run's words change, so the name sits exactly where the template put the prompt.
    title_runs = shape(s, "Title").text_frame.paragraphs[0].runs
    next(r for r in title_runs if r.text == "IDEA TITLE").text = "TRACKSEN"
    fill_team_oval(s, team)
    heading, p1, p2, p3 = pointers(s, 0.40, 1.16, 6.50, size=14.0, heading_size=14.0)

    answer(heading, [
        par([B(IDEA_TITLE)], size=12.0, marL=0.375, indent=0, bullet=None, before=5),
    ])
    answer(p1, [
        par([B("Integrates"), " TMS (P.Way), SMMS (S&T) and TDMS (TRD) defects with the "
             "timetable, goods forecast and corridor windows — one task model keyed by "
             "section, line and chainage"]),
        par([B("AI ranks every task:"), " failure risk × urgency × consequence = a "
             "Criticality Index with SHAP reasons, plus each job’s real duration (P90)"]),
        par([B("OR-Tools CP-SAT"), " builds the weekly (15-min) and monthly (corridor-slot) "
             "plan; officers run what-ifs, re-solve and sanction"]),
    ])
    answer(p2, [
        par([B("Clubs the three departments"), " into one line closure, inside the mandated "
             "corridor, never across a premier train path"]),
        par([B("Critical defects go first,"), " and blocks are sized to the real work so they "
             "do not burst"]),
    ])
    answer(p3, [
        par([B("Maximises risk retired per block-hour,"), " not tasks completed"]),
        par([B("Built on IR’s own rules:"), " the 2016 integrated corridor-block circular, "
             "the Rolling Block Programme, the DRM sanction route"]),
        par([B("Recommends, never grants:"), " every approval on a tamper-evident, "
             "hash-chained trail"]),
    ])

    # ---- right: one section, one day, before and after
    box(s, RX, TOP, RW, 3.78, fill=PALE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    label(s, RX + 0.22, TOP + 0.10, RW - 0.44, 0.26,
          [B("ONE BLOCK SECTION, ONE DAY", GREY)], size=9.5)

    def lane(y, title, colour, pale, blocks, tally):
        label(s, RX + 0.22, y, 3.6, 0.24, [B(title, colour)], size=10.5)
        label(s, RX + RW - 2.02, y, 1.80, 0.24, [B(tally, colour)], size=10.5, align="r")
        gx, gy, gw, gh = RX + 0.22, y + 0.30, RW - 0.44, 1.02
        box(s, gx, gy, gw, gh, fill=WHITE, line=RULE, lw=0.5)
        cx, cw = gx + gw * 10 / 24, gw * 4 / 24           # corridor 10:00-14:00
        box(s, cx, gy, cw, gh, fill=pale)
        label(s, cx - 0.30, gy + gh + 0.01, cw + 0.60, 0.18,
              [B("corridor 10–14", BLUE)], size=7.5, align="ctr")
        for hh in (0, 6, 18, 24):
            label(s, gx + gw * hh / 24 - 0.25, gy + gh + 0.01, 0.5, 0.18,
                  [(f"{hh:02d}:00", {"color": GREY})], size=7, align="ctr")
        row_h = gh / 3
        for start, hours, row, text in blocks:
            bx = gx + gw * start / 24
            box(s, bx, gy + row * row_h + 0.05, gw * hours / 24, row_h - 0.10, fill=colour)
            label(s, bx, gy + row * row_h + 0.05, gw * hours / 24, row_h - 0.10,
                  [B(text, WHITE)], size=8, align="ctr")

    lane(TOP + 0.42, "Today: three departments ask alone", RED, "E3ECF6",
         [(3.0, 3.0, 0, "ENGG"), (11.0, 3.0, 1, "S&T"), (17.0, 3.0, 2, "TRD")],
         "3 closures · 9 block-hrs")
    label(s, RX + 0.22, TOP + 1.97, RW - 0.44, 0.26,
          [B("▼  TRACKSEN clubs them into the corridor", BLUE)], size=10, align="ctr")
    lane(TOP + 2.24, "TRACKSEN: one integrated block", GREEN, "E3ECF6",
         [(10.0, 4.0, 0, "ENGG"), (10.0, 4.0, 1, "S&T"), (10.0, 4.0, 2, "TRD")],
         "1 closure · 4 block-hrs")

    # ---- right: the two numbers that frame it
    ty, th, tw = TOP + 3.92, BOTTOM - TOP - 3.92, (RW - 0.14) / 2
    tiles = [
        ("2.2%", RED, PALE_RED, "of blocks across 11 zones were integrated in March 2019; "
         "97.8% were taken in isolation (CAG)"),
        ("−48", GREEN, PALE_GREEN, "line closures in one week on the Danapur division for "
         "the same 190 jobs (our prototype)"),
    ]
    for i, (big, colour, pale, text) in enumerate(tiles):
        x = RX + i * (tw + 0.14)
        box(s, x, ty, tw, th, fill=pale, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        tf = textbox(s, x + 0.16, ty + 0.08, tw - 0.32, th - 0.16, MSO_ANCHOR.MIDDLE)
        write(tf, [par([B(big, colour)], size=26, marL=0, indent=0, bullet=None, before=0),
                   par([text], size=9, marL=0, indent=0, bullet=None, before=2)])


# ------------------------------------------------------------------ slide 3
def crop(src: Path, box_px, out: Path) -> Path:
    Image.open(src).crop(box_px).save(out)
    return out


def slide_technical(s, team, shots: Path, tmp: Path):
    fill_team_oval(s, team)
    p1, p2 = pointers(s, 0.40, 1.16, 6.45, size=14.0)

    answer(p1, [
        par([B("AI / ML:"), " LightGBM (failure risk; quantile P50/P90 duration), Cox survival "
             "model, conformal calibration, SHAP explanations, scikit-learn"]),
        par([B("Optimisation:"), " Google OR-Tools CP-SAT — interval variables, NoOverlap "
             "per section and line, parallel search"]),
        par([B("Software:"), " Python, FastAPI, pandas · Next.js, React, TypeScript, "
             "custom SVG train graph"]),
        par([B("Security & deployment:"), " scrypt accounts, revocable sessions, SHA-256 "
             "hash-chained audit · on-premise (RailTel / NIC), PostgreSQL + PostGIS"]),
    ])

    # ---- left, under pointer 2: the process as a flow chart
    steps = [
        ("1  Ingest", "Read-only adapters\nREST → DB view → CSV"),
        ("2  Unify", "One task model keyed by\nsection, line, chainage"),
        ("3  Predict", "Criticality, time to failure,\nP90 duration, traffic cost"),
        ("4  Optimise", "CP-SAT: weekly 15-min grid,\nmonthly corridor slots"),
        ("5  Sanction", "What-if, pin & re-solve;\nconcur → clear → DRM"),
        ("6  Report", "Weekly DRM and monthly\nGM returns (para 3.0)"),
    ]
    fy, fw, fh, gap = 3.98, 2.03, 0.84, 0.18
    for i, (head, sub) in enumerate(steps):
        col, row = i % 3, i // 3
        x = 0.40 + col * (fw + gap)
        y = fy + row * (fh + 0.14)
        fill = NAVY if i < 4 else BLUE
        box(s, x, y, fw, fh, fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.10)
        tf = textbox(s, x + 0.10, y + 0.05, fw - 0.20, fh - 0.10, MSO_ANCHOR.MIDDLE)
        write(tf, [par([B(head, WHITE)], size=10.5, marL=0, indent=0, bullet=None, before=0,
                       align="ctr")] +
                  [par([(line, {"color": "DCE6F2"})], size=8, marL=0, indent=0, bullet=None,
                       before=1, align="ctr") for line in sub.split("\n")])
        if col < 2:
            label(s, x + fw, y, gap, fh, [B("›", GREY)], size=14, align="ctr")
    oy = fy + 2 * fh + 0.28
    box(s, 0.40, oy, 6.45, 0.92, fill=PALE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    tf = textbox(s, 0.56, oy + 0.06, 6.13, 0.80, MSO_ANCHOR.MIDDLE)
    write(tf, [
        par([B("max  Σ Criticality + β·Clubbing + Corridor − λ·Traffic "
               "− μ·Overdue", NAVY)], size=11, marL=0, indent=0, bullet=None,
            before=0, align="ctr"),
        par([("subject to line exclusivity · one gang per department per block · "
              "machine positioning · staff and night-work limits · no block across a "
              "premier path", {"color": GREY})], size=9, marL=0, indent=0, bullet=None,
            before=3, align="ctr"),
    ])

    # ---- right: the working prototype
    plan = crop(shots / "planning.png", (378, 284, 2370, 1338), tmp / "planning_crop.png")
    intel = crop(shots / "intelligence.png", (972, 528, 2370, 1080), tmp / "intel_crop.png")
    label(s, RX, TOP, RW, 0.24, [B("Working prototype — ", NAVY),
                                 ("block plan on a time–distance train graph", {"color": GREY})],
          size=10)
    w1 = RW
    h1 = w1 * (1338 - 284) / (2370 - 378)
    pic = s.shapes.add_picture(str(plan), Inches(RX), Inches(TOP + 0.28), Inches(w1), Inches(h1))
    pic.line.color.rgb = rgb(RULE)
    y2 = TOP + 0.28 + h1 + 0.12
    label(s, RX, y2, RW, 0.24, [B("AI ranking — ", NAVY),
                                ("why a job is ranked first, in SHAP terms", {"color": GREY})],
          size=10)
    h2 = BOTTOM - (y2 + 0.28)
    w2 = h2 * (2370 - 972) / (1080 - 528)
    pic = s.shapes.add_picture(str(intel), Inches(RX + (RW - w2) / 2), Inches(y2 + 0.28),
                               Inches(w2), Inches(h2))
    pic.line.color.rgb = rgb(RULE)


# ------------------------------------------------------------------ slide 4
def slide_feasibility(s, team):
    fill_team_oval(s, team)
    p1, p2, p3 = pointers(s, 0.40, 1.16, 6.45, size=14.0)

    answer(p1, [
        par([B("The data already exists:"), " TMS, SMMS, TDMS, the Control Office and the "
             "working timetable hold every input — no new hardware"]),
        par([B("Non-intrusive:"), " read-only adapters never write to a source system; a "
             "nightly file drop is enough where there is no API"]),
        par([B("Proven at division scale:"), " 600 tasks × 7 days solved in 4 minutes on "
             "one machine; 296 automated tests"]),
    ])
    answer(p2, [
        par(["Legacy systems without APIs, each with its own units and severity scales"]),
        par(["Incomplete or inconsistent defect records"]),
        par(["Officers trusting an algorithm’s ranking"]),
        par(["Disruptions after a plan is sanctioned"]),
    ])
    answer(p3, [
        par([B("Adapter ladder:"), " REST → DB view → CSV, with unit and severity "
             "translation tested"]),
        par([B("Reject by name:"), " every unmappable record is reported with its reason, "
             "never silently dropped"]),
        par([B("Explainable and advisory:"), " SHAP reasons, visible weights; an officer can "
             "move any block"]),
        par([B("Pin and re-solve:"), " fix what is decided, re-plan the rest in seconds"]),
    ])

    # ---- right: path to deployment
    box(s, RX, TOP, RW, 3.20, fill=PALE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
    label(s, RX + 0.22, TOP + 0.10, RW - 0.44, 0.26, [B("PATH TO DEPLOYMENT", GREY)], size=9.5)
    steps = [
        ("Shadow pilot", "one division, run beside the existing Rolling Block Programme"),
        ("Measure", "KPIs against current practice, in the weekly DRM / monthly GM returns"),
        ("Connect", "live read-only feeds, and actual block outcomes to retrain the models"),
        ("Scale", "zone-wide, then alongside ROBMS across Indian Railways"),
    ]
    sy = TOP + 0.46
    for i, (head, text) in enumerate(steps):
        y = sy + i * 0.67
        box(s, RX + 0.24, y + 0.06, 0.42, 0.42, fill=BLUE, shape=MSO_SHAPE.OVAL)
        label(s, RX + 0.24, y + 0.06, 0.42, 0.42, [B(str(i + 1), WHITE)], size=12, align="ctr")
        if i < len(steps) - 1:
            box(s, RX + 0.435, y + 0.48, 0.03, 0.25, fill=RULE)
        tf = textbox(s, RX + 0.84, y + 0.02, RW - 1.06, 0.56, MSO_ANCHOR.MIDDLE)
        write(tf, [par([B(head), "  " + text], size=10.5, marL=0, indent=0, bullet=None,
                       before=0)])

    # ---- right: why it is viable
    facts = [
        ("0", "new hardware or data collection"),
        ("100%", "on-premise — data stays inside IR"),
        ("Open", "source stack (OR-Tools, Apache-2.0)"),
        ("50:50", "prototype cost-sharing under the Rail Tech Policy, 2026"),
    ]
    fy = TOP + 3.34
    fw, fh = (RW - 0.14) / 2, (BOTTOM - fy - 0.14) / 2
    for i, (big, text) in enumerate(facts):
        x = RX + (i % 2) * (fw + 0.14)
        y = fy + (i // 2) * (fh + 0.14)
        box(s, x, y, fw, fh, fill=WHITE, line=RULE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        tf = textbox(s, x + 0.16, y + 0.06, fw - 0.32, fh - 0.12, MSO_ANCHOR.MIDDLE)
        write(tf, [par([B(big, BLUE)], size=20, marL=0, indent=0, bullet=None, before=0),
                   par([text], size=9.5, marL=0, indent=0, bullet=None, before=1)])


# ------------------------------------------------------------------ slide 5
def slide_impact(s, team):
    fill_team_oval(s, team)
    p1, p2 = pointers(s, 0.40, 1.16, 6.45, size=14.0)

    answer(p1, [
        par([B("Divisional planners:"), " one ranked queue across Engineering, S&T and TRD "
             "instead of three blind ones — a plan in minutes, not a weekly spreadsheet"]),
        par([B("Operations (Sr.DOM, Control):"), " blocks land in the quietest windows; "
             "traffic detention cost down 38%"]),
        par([B("Sanctioning officers:"), " one explainable plan, with a tamper-evident record "
             "of who approved what"]),
        par([B("Passengers and freight:"), " fewer detentions and fewer assets failing in "
             "service"]),
    ])
    answer(p2, [
        par([B("Safety:"), " the most failure-prone defects are attended first — "
             "high-criticality unplanned failures 17 → 13"]),
        par([B("Economic:"), " 48 fewer line closures and 175 fewer block-hours a week on one "
             "division, freeing paths for trains"]),
        par([B("Social:"), " better punctuality — 86% of blocks as demanded would burst; "
             "at the predicted P90, 8% would"]),
        par([B("Environmental:"), " fewer unplanned halts and speed restrictions mean less "
             "idling and fewer braking cycles"]),
        par([B("Institutional:"), " puts the 2016 integrated-block circular into daily "
             "practice, and survives officer transfers"]),
    ])

    # ---- right: headline results
    stats = [("+129%", "risk retired per block-hour", "7.8 → 17.9"),
             ("−48", "line closures a week", "190 → 142 blocks"),
             ("−38%", "traffic detention cost", "129k → 81k wtd min")]
    tw = (RW - 0.24) / 3
    for i, (big, what, how) in enumerate(stats):
        x = RX + i * (tw + 0.12)
        fill, fg, sub = (NAVY, WHITE, "C9D8EC") if i == 0 else (PALE, NAVY, GREY)
        box(s, x, TOP, tw, 1.34, fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        tf = textbox(s, x + 0.12, TOP + 0.08, tw - 0.24, 1.18, MSO_ANCHOR.MIDDLE)
        write(tf, [par([B(big, fg)], size=24, marL=0, indent=0, bullet=None, before=0, align="ctr"),
                   par([B(what, fg)], size=9.5, marL=0, indent=0, bullet=None, before=1, align="ctr"),
                   par([(how, {"color": sub})], size=9, marL=0, indent=0, bullet=None, before=1,
                       align="ctr")])

    cy = TOP + 1.48
    box(s, RX, cy, RW, BOTTOM - cy, fill=WHITE, line=RULE, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        radius=0.03)
    label(s, RX + 0.20, cy + 0.08, RW - 0.40, 0.26,
          [B("TRACKSEN vs current practice", NAVY), ("   (current practice = 100)", {"color": GREY})],
          size=10.5)
    data = CategoryChartData()
    data.categories = ["Traffic cost", "Block-hours", "Line closures", "Corridor adherence",
                       "Risk retired per block-hour"]
    data.add_series("Current practice (first come, first served)", (100, 100, 100, 100, 100))
    data.add_series("TRACKSEN", (62, 73, 75, 149, 229))
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(RX + 0.10), Inches(cy + 0.36),
                            Inches(RW - 0.20), Inches(BOTTOM - cy - 0.84), data)
    ch = gf.chart
    ch.has_title = False
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(9)
    ch.legend.font.name = FONT
    plot = ch.plots[0]
    plot.gap_width = 50
    plot.overlap = -10
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(9)
    plot.data_labels.font.bold = True
    plot.data_labels.font.name = FONT
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for series, colour in zip(ch.series, ("BFC9D6", BLUE)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = rgb(colour)
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(9)
    ca.tick_labels.font.name = FONT
    ca.format.line.color.rgb = rgb(RULE)
    va = ch.value_axis
    va.visible = False
    va.has_major_gridlines = False
    va.maximum_scale, va.minimum_scale = 255.0, 0.0
    label(s, RX + 0.20, BOTTOM - 0.46, RW - 0.40, 0.40,
          [("Danapur division, East Central Railway · 7 days · 600 tasks · "
            "published 543-train timetable · synthetic defect data · same physical "
            "constraints for both plans", {"italic": True, "color": GREY})], size=8, line=0.95)


# ------------------------------------------------------------------ slide 6
REFERENCES = [
    ("Policy and statutory basis", [
        ("Railway Board, Fixed-Time Integrated Corridor Blocks, No. 2015/Track-III/TK/5/Pt.I, "
         "29.12.2016, with the Joint Circular of AM/CE and AM/Traffic",
         "https://indianrailways.gov.in/railwayboard/uploads/directorate/tracks/Track_3/"
         "Corridor_Block_291216.pdf"),
        ("Indian Railways Track Machines Manual, Ch. 5 — planning and monitoring of "
         "track machines",
         "https://indianrailways.gov.in/railwayboard/uploads/codesmanual/IRTMM-RDSO/TMM_Ch/"
         "TMM_Ch_5.html"),
        ("S. Prajapati, Rolling Block — Paradigm Shift in Inspection and Maintenance, "
         "IRICEN/IPWE seminar, Nov 2023",
         "https://iricen.gov.in/iricen/ipwe_seminar/2017/Nov%202023%20Vol-1/"
         "Rolling%20Block%20-%20Paradigm%205.pdf"),
    ]),
    ("Audit evidence", [
        ("CAG / RTI Kolkata, Case Study on Punctuality and Travel Time in Train Operations, "
         "July 2023 (from Compliance Report No. 22 of 2021)",
         "https://cag.gov.in/uploads/research_paper/RES-220900-Peer-Reviewed-Case-Study-on-"
         "Punctuality-20230807-052050-1-068f089ca70b4b7-79400532.pdf"),
        ("CAG, Compliance Audit on Maintenance of Track on Heavy Traffic Sections, Report "
         "No. 45 of 2018",
         "https://cag.gov.in/uploads/download_audit_report/2017/Report_No.45_of_2018_%E2%80%93_"
         "Compliance_Audit_on_Maintenance_of_track_on_heavy_traffic_sections_over_India.pdf"),
    ]),
    ("Data behind the prototype", [
        ("Published timetable: IRCTC schedule dataset merged with NTES running days, crawled "
         "with railpull — 543 services over the Danapur division",
         "https://github.com/shwetankg07/railpull"),
    ]),
]
REFERENCES_RIGHT = [
    ("Systems TRACKSEN sits beside", [
        ("CRIS project list — TMS, SMMS, TDMS, TMMS, COA, ICMS, RTIS",
         "https://cris.org.in/loadpage?page=ProjectListPage"),
        ("Track Management System · SMMS · ROBMS (Rolling Block Management System)",
         "https://ircep.gov.in/TMS/  ·  https://smms.indianrailways.gov.in/  ·  "
         "https://robms.indianrailways.gov.in/ROBMS/"),
    ]),
    ("Technical and academic", [
        ("Google OR-Tools CP-SAT solver — scheduling with interval variables",
         "https://developers.google.com/optimization/cp"),
        ("Lundberg & Lee, A Unified Approach to Interpreting Model Predictions (SHAP), "
         "NeurIPS 2017", "https://github.com/shap/shap"),
        ("Liao et al., Prediction Models for Railway Track Geometry Degradation Using "
         "Machine Learning Methods: A Review, 2022",
         "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9570632/"),
    ]),
    ("Current Indian Railways technology", [
        ("PIB — Real Time Information System: ISRO loco GPS every 30 s into the Control "
         "Office Application", "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=1861729"),
        ("NAIR — Simulation and its Potential for Indian Railways (capacity simulation)",
         "https://nair.indianrailways.gov.in/uploads/files/1468474436130-Simulation%20-%20"
         "Potential%20for%20Indian%20Railways-%20Rajnish%20Kumar.pdf"),
        ("Rail Tech Policy, 26 February 2026 — cost-shared prototype trials",
         "https://metrorailnews.in/railway-minister-announces-rail-tech-policy/"),
    ]),
]


def slide_references(s, team):
    fill_team_oval(s, team)
    (p1,) = pointers(s, 0.40, 1.16, 12.53, size=14.0)

    def column(x, groups):
        tf = textbox(s, x, 1.66, 6.12, BOTTOM - 1.66)
        paras = []
        for gi, (head, items) in enumerate(groups):
            paras.append(par([B(head.upper(), BLUE)], size=10, marL=0, indent=0, bullet=None,
                             before=0 if gi == 0 else 9))
            for text, url in items:
                paras.append(par([text], size=10, marL=0.20, indent=-0.17, before=4))
                paras.append(par([(url, {"color": BLUE, "size": 8})], size=8, marL=0.20,
                                 indent=0, bullet=None, before=1))
        write(tf, paras)
        for p in tf.paragraphs:                         # make every link clickable in the PDF
            for r in p.runs:
                if r.text.startswith("https://"):
                    r.hyperlink.address = r.text.split("  ")[0]

    column(0.40, REFERENCES)
    column(6.81, REFERENCES_RIGHT)


# ------------------------------------------------------------------ assembly
def drop_slide(prs, index):
    ids = prs.slides._sldIdLst
    sld = list(ids)[index]
    prs.part.drop_rel(sld.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
    ids.remove(sld)


def export_pdf(pptx: Path, pdf: Path):
    """PowerPoint's own exporter, so the PDF is what PowerPoint renders."""
    script = (
        "$pp = New-Object -ComObject PowerPoint.Application; "
        f"$p = $pp.Presentations.Open('{pptx}', $true, $false, $false); "
        f"$p.SaveAs('{pdf}', 32); $p.Close()"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--template", required=True, type=Path)
    ap.add_argument("--team-name", default="[Team Name]")
    ap.add_argument("--team-id", default="[Team ID]")
    ap.add_argument("--shots", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/TRACKSEN_SIH2026_PS26027.pptx"))
    ap.add_argument("--pdf", action="store_true", help="also export a PDF (needs PowerPoint)")
    args = ap.parse_args(argv)

    prs = Presentation(str(args.template))
    s1, s2, s3, s4, s5, s6 = list(prs.slides)[:6]
    with tempfile.TemporaryDirectory() as tmp:
        fill_title_slide(s1, args.team_id, args.team_name)
        slide_idea(s2, args.team_name)
        slide_technical(s3, args.team_name, args.shots, Path(tmp))
        slide_feasibility(s4, args.team_name)
        slide_impact(s5, args.team_name)
        slide_references(s6, args.team_name)
        drop_slide(prs, 6)                              # the template's instructions slide
        args.out.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(args.out))
    print("saved", args.out)
    if args.pdf:
        pdf = args.out.with_suffix(".pdf")
        export_pdf(args.out.resolve(), pdf.resolve())
        print("saved", pdf)


if __name__ == "__main__":
    sys.exit(main())
