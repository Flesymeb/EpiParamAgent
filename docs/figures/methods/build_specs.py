"""Rebuild deterministic FigureSpec sources; no result data or model calls."""

from pathlib import Path
import json

OUT = Path(__file__).resolve().parent
INK = "#29343E"
MUTED = "#667582"
BLUE = "#6F91AF"
GREEN = "#739B88"
GOLD = "#B4926F"
LINE = "#71828D"


def spec(title, w, h):
    return {
        "title": title,
        "canvas": {"width": w, "height": h},
        "style": {
            "font_family": "Noto Sans, DejaVu Sans, sans-serif",
            "font_size": 20,
            "bg_color": "#FFFFFF",
        },
        "nodes": [],
        "edges": [],
        "labels": [],
    }


def n(s, id, label, x, y, w=270, h=72, c=LINE, fill="#FFFFFF", fs=20):
    s["nodes"].append(
        dict(
            id=id,
            label=label,
            x=x,
            y=y,
            width=w,
            height=h,
            shape="rounded",
            fill=fill,
            stroke=c,
            text_color=INK,
            font_size=fs,
        )
    )


def e(s, a, b, label="", c=LINE, dash=False, curve=False):
    s["edges"].append(
        {
            "from": a,
            "to": b,
            "label": label,
            "color": c,
            "style": "dashed" if dash else "solid",
            "thickness": 2,
            "curve": curve,
        }
    )


def t(s, text, x, y, fs=20, c=MUTED, anchor="middle"):
    s["labels"].append(dict(text=text, x=x, y=y, font_size=fs, color=c, anchor=anchor))


s = spec(
    "MetaAgent-Epi: end-to-end pipeline and three independently callable modules",
    1700,
    1140,
)
t(s, "(a) End-to-end review with three callable modules", 50, 45, 30, INK, "start")
for id, label, x, w, c, f in [
    ("query", "Question &\nquery / retrieval", 110, 185, LINE, "#F6F8FA"),
    ("screen", "Screening", 350, 245, BLUE, "#F0F6FA"),
    ("coding", "Coding", 850, 245, GREEN, "#F0F6F1"),
    ("synth", "Synthesis", 1350, 245, GOLD, "#FAF5EF"),
    ("report", "Verified artifacts\n+ review status", 1585, 190, LINE, "#F6F8FA"),
]:
    n(
        s,
        id,
        label,
        x,
        140,
        w,
        80,
        c,
        f,
        23 if id in ["screen", "coding", "synth"] else 19,
    )
e(s, "query", "screen", "records")
e(s, "screen", "coding", "retained, screened full texts")
e(s, "coding", "synth", "evidence-linked estimates")
e(s, "synth", "report")
for x, title, sub, c in [
    (350, "(b) Screening", "Record input: JSONL / CSV / bibliography", BLUE),
    (850, "(c) Coding", "Document input: primary full text + codebook", GREEN),
    (1350, "(d) Pi Synthesis", "Table input + methods / primary sources", GOLD),
]:
    t(s, title, x, 255, 26, INK)
    t(s, sub, x, 293, 18, c)
# Open screening mechanism; pending is not an automatic exclusion.
n(
    s,
    "meta",
    "Title • abstract • metadata\nOfficial dates, keywords, native MeSH",
    350,
    365,
    350,
    78,
    BLUE,
    "#FAFCFD",
    19,
)
n(
    s,
    "ta",
    "Title / abstract screening\nFive dimensions or review criteria",
    350,
    465,
    350,
    76,
    BLUE,
    "#FAFCFD",
    19,
)
n(
    s,
    "cache",
    "paper_pool: verified parsed cache\nHIT → reuse; MISS → PDF + MinerU",
    350,
    585,
    350,
    86,
    BLUE,
    "#F4F8FB",
    19,
)
n(
    s,
    "ft",
    "Full-text screening\nEvidence + source coverage checks",
    350,
    705,
    350,
    76,
    BLUE,
    "#FAFCFD",
    19,
)
n(
    s,
    "accepted",
    "Retained + status=screened\nS / P according to active policy",
    350,
    817,
    350,
    76,
    BLUE,
    "#F2F7F5",
    19,
)
n(
    s,
    "pending",
    "Unresolved / pending\nreview, source repair, resume",
    350,
    945,
    350,
    78,
    "#AE946A",
    "#FBF8F0",
    19,
)
e(s, "meta", "ta", c=BLUE)
e(s, "ta", "cache", "S / P or needs full text", BLUE)
e(s, "cache", "ft", c=BLUE)
e(s, "ft", "accepted", c=BLUE)
e(s, "ft", "pending", "flagged review / missing source", BLUE, True, True)
t(s, "Grounded exclusion exits; missing source remains unresolved.", 350, 1025, 17)
# Default full A+B, not a separate external LangExtract module.
n(
    s,
    "fulltext",
    "Verified source text / blocks\nQuestion + effective codebook",
    850,
    365,
    350,
    78,
    GREEN,
    "#FAFCFA",
    19,
)
n(
    s,
    "a",
    "A  Candidate extraction\nLangExtract / explicit LLM backend",
    850,
    475,
    350,
    80,
    GREEN,
    "#F4F8F2",
    20,
)
n(
    s,
    "b",
    "B  Semantic finalization\nSource-bound fields and dispositions",
    850,
    610,
    350,
    88,
    GREEN,
    "#F4F8F2",
    20,
)
e(s, "fulltext", "a", c=GREEN)
e(s, "a", "b", "candidates + exact source evidence", GREEN)
t(s, "Keep • correct • reject • pending", 850, 700, 20, GREEN)
# Small schematic coding table, no invented numerical example.
for j, (head, val) in enumerate(
    [
        ("Estimate", "value + statistic"),
        ("Context", "cohort / group"),
        ("Evidence", "quote + locator"),
    ]
):
    x = 730 + j * 120
    n(s, "ch" + str(j), head, x, 758, 120, 42, GREEN, "#EFF5EE", 17)
    n(s, "cv" + str(j), val, x, 804, 120, 50, "#B4C7B9", "#FFFFFF", 14)
e(s, "b", "ch1", c=GREEN)
t(s, "Evidence-linked table + original values / review flags", 850, 875, 18)
t(s, "Default: full A+B. Remove A or B only by explicit ablation.", 850, 945, 17)
t(s, "FT and Coding share identity / version / SHA-bound source caches.", 850, 1025, 17)
# Actual Pi tool loop and publication gate.
n(
    s,
    "profile",
    "Profile / SQL / evidence\nRead table schema and staged sources",
    1350,
    365,
    350,
    78,
    GOLD,
    "#FDFBF8",
    19,
)
n(
    s,
    "plan",
    "Commit one estimand + analysis plan\nSelection • units • uncertainty • dependence",
    1350,
    480,
    360,
    92,
    GOLD,
    "#FAF5EF",
    19,
)
n(s, "code", "Write code\nPython / R", 1250, 625, 200, 76, GOLD, "#FDFBF8", 20)
n(s, "execute", "Sandbox execute\n+ validate", 1460, 735, 240, 78, GOLD, "#FDFBF8", 20)
n(
    s,
    "finalize",
    "Finalize verified execution\nCode • ledger • plots • report",
    1350,
    865,
    350,
    84,
    GOLD,
    "#FAF5EF",
    20,
)
e(s, "profile", "plan", c=GOLD)
e(s, "plan", "code", c=GOLD)
e(s, "code", "execute", c=GOLD)
e(s, "execute", "finalize", c=GOLD)
e(s, "execute", "plan", "bounded feedback", GOLD, True, True)
t(s, "Pending is explicit; runtime success ≠ scientific validation.", 1350, 945, 17)
t(s, "Whole method documents may expose original SR results.", 1350, 1025, 17, GOLD)
n(
    s,
    "context",
    "Shared context: research question • review protocol • codebook • analysis settings",
    850,
    1095,
    1580,
    48,
    "#EDF1F3",
    "#F4F6F7",
    21,
)
(OUT / "end_to_end.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
# Separate construction / evaluation figure: no counts that belong to another release.
s = spec("Versioned benchmark construction and layered evaluation", 1650, 1120)
t(s, "(a) Source-grounded, versioned benchmark construction", 50, 45, 29, INK, "start")
n(
    s,
    "query",
    "Declared query / database routes\nSearch date and time policy",
    190,
    165,
    315,
    82,
    BLUE,
    "#F7FAFC",
    20,
)
n(
    s,
    "original",
    "Original SR tables / figures / SI\nFinal roster + bibliography",
    190,
    335,
    315,
    86,
    BLUE,
    "#F7FAFC",
    20,
)
n(
    s,
    "identity",
    "Resolve report identity / version\nDOI • PMID • title • original anchors",
    555,
    335,
    330,
    86,
    GREEN,
    "#F6FAF6",
    20,
)
n(
    s,
    "raw",
    "raw_search\nNaturally returned records",
    925,
    165,
    290,
    82,
    BLUE,
    "#F0F6FA",
    21,
)
n(
    s,
    "manual",
    "manual additions\nSource-rescued records, separate",
    925,
    335,
    290,
    86,
    "#AE946A",
    "#FBF8F0",
    20,
)
n(
    s,
    "release",
    "Versioned release / raw_pool\nDedup links + separate pool views",
    1285,
    245,
    320,
    88,
    GREEN,
    "#F2F7F2",
    20,
)
e(s, "query", "raw", "native retrieval", BLUE)
e(s, "original", "identity", c=GREEN)
e(s, "identity", "manual", "provenance retained", GREEN)
e(s, "raw", "release", c=BLUE)
e(s, "manual", "release", c="#AE946A")
t(
    s,
    "Natural retrieval and manual rescue are not one recall denominator.",
    925,
    425,
    19,
)
t(
    s,
    "Membership, target-analysis contribution and independent-study units remain distinct.",
    800,
    480,
    20,
    INK,
)
# Keep model inputs and offline references as separate lanes.
t(s, "(b) Model inputs, predictions and offline comparison", 50, 555, 29, INK, "start")
n(
    s,
    "ref",
    "Offline reference snapshots\nHistorical membership / coding / synthesis",
    355,
    665,
    440,
    88,
    "#9C8E82",
    "#FAF8F5",
    20,
)
n(
    s,
    "input",
    "Model input projection\nMetadata • task • available documents",
    1285,
    600,
    355,
    86,
    BLUE,
    "#F3F8FB",
    20,
)
e(s, "release", "input", "choose explicit pool", BLUE)
n(
    s,
    "inference",
    "Screening → Coding A+B → Pi\nRun-bound predictions + error coverage",
    1285,
    735,
    355,
    88,
    GREEN,
    "#F4F8F3",
    20,
)
e(s, "input", "inference", c=GREEN)
e(s, "identity", "ref", "source-linked labels", c="#9C8E82", dash=True)
n(
    s,
    "join",
    "Offline, layer-specific evaluation\nExact IDs / scope / denominators",
    820,
    845,
    370,
    80,
    LINE,
    "#F7F9FA",
    21,
)
e(s, "ref", "join", "not injected as label tables", c="#9C8E82", dash=True)
e(s, "inference", "join", "predictions", c=GREEN)
for id, label, x, c in [
    (
        "screen_eval",
        "Retrieval / screening\nNatural recall; pool P / R / F1\nHistorical member ≠ eligibility gold",
        310,
        BLUE,
    ),
    (
        "coding_eval",
        "Coding fields + evidence\nCoverage, precision, omissions\nDuplicates and source support",
        820,
        GREEN,
    ),
    (
        "synth_eval",
        "Synthesis: separate conclusions\nExecution / math • scientific validity\nOriginal-SR reproduction",
        1330,
        GOLD,
    ),
]:
    n(s, id, label, x, 1000, 455, 112, c, "#FFFFFF", 19)
    e(s, "join", id, c=c)
t(
    s,
    "Method-source full text can contain SR results; semantic answer masking is not guaranteed.",
    825,
    1093,
    20,
    GOLD,
)
(OUT / "benchmark.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
# Visual QA refinement remains in the spec generator, never hand-edits SVG.
p = OUT / "end_to_end.json"
s = json.loads(p.read_text())
by = {n["id"]: n for n in s["nodes"]}
for id, label in {
    "meta": "Title • abstract • metadata\nDates • keywords • native MeSH",
    "ta": "Title / abstract screening\nFive dimensions / review criteria",
    "cache": "Verified paper_pool cache\nHit: reuse • miss: PDF + MinerU",
    "ft": "Full-text screening\nEvidence / coverage checks",
    "accepted": "Retained + screened\nS / P per active policy",
    "pending": "Unresolved\nReview / repair / resume",
    "fulltext": "Verified source text / blocks\nQuestion + effective codebook",
    "a": "A  Candidate extraction\nLangExtract / explicit LLM",
    "b": "B  Semantic finalization\nSource-bound fields + decisions",
    "profile": "Profile • SQL • evidence\nInspect table / staged sources",
    "plan": "Commit common estimand + plan\nSelect • transform • dependence",
}.items():
    by[id]["label"] = label
by["pending"].update(x=110, width=200, font_size=17)
s["edges"] = [e for e in s["edges"] if not (e["from"] == "ft" and e["to"] == "pending")]
n(s, "pending_branch", "•", 110, 705, 8, 8, BLUE, BLUE, 6)
e(s, "ft", "pending_branch", c=BLUE, dash=True)
e(s, "pending_branch", "pending", c=BLUE, dash=True)
for edge in s["edges"]:
    if (edge["from"], edge["to"]) in [("query", "screen"), ("execute", "plan")]:
        edge["label"] = ""
for l in s["labels"]:
    if l["text"].startswith("Default:"):
        l["text"] = "Full A+B default; explicit ablations only."
    if l["text"].startswith("Pending is explicit"):
        l["text"] = "Pending explicit; execution ≠ scientific validation."
    if l["text"].startswith("Grounded exclusion"):
        l["text"] = "Missing source ≠ exclusion."
    if l["text"].startswith("FT and Coding share"):
        l["text"] = "FT + Coding share verified source caches."
    if l["text"].startswith("Whole method"):
        l["text"] = "Whole SR methods may expose results."
    if l["text"].startswith("Table input"):
        l["text"] = "Table + methods + primary evidence"
t(s, "bounded feedback", 1535, 600, 16, GOLD)
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
p = OUT / "benchmark.json"
s = json.loads(p.read_text())
by = {n["id"]: n for n in s["nodes"]}
for id, label in {
    "query": "Declared query + routes\nSearch date / time policy",
    "original": "SR tables • figures • SI\nFinal roster + bibliography",
    "identity": "Report identity + version\nDOI • PMID • source anchors",
    "raw": "raw_search\nNatural query returns",
    "manual": "manual additions\nSource-rescued, separate",
    "release": "Versioned release / pools\nProvenance + dedup links",
    "ref": "Offline reference snapshots\nMembership • coding • synthesis",
    "input": "Model input projection\nTask • metadata • documents",
    "inference": "Screening → Coding A+B → Pi\nPredictions • errors • provenance",
    "join": "Offline evaluation\nIDs • scope • denominators",
}.items():
    by[id]["label"] = label
by["ref"]["x"] = 555
for edge in s["edges"]:
    if (edge["from"], edge["to"]) == ("identity", "ref"):
        edge["label"] = ""
for l in s["labels"]:
    if l["text"].startswith("(b)"):
        l["text"] = "(b) Evaluation layers"
    if l["text"].startswith("Natural retrieval"):
        l["text"] = "Keep natural and manual denominators separate."
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
p = OUT / "end_to_end.json"
s = json.loads(p.read_text())
next(n for n in s["nodes"] if n["id"] == "pending")["label"] = (
    "Unresolved\nReview / resume"
)
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
p = OUT / "benchmark.json"
s = json.loads(p.read_text())
for edge in s["edges"]:
    if (edge["from"], edge["to"]) == ("identity", "manual"):
        edge["label"] = ""
for l in s["labels"]:
    if l["text"].startswith("Membership, target-analysis"):
        l.update(text="Report, estimate and cohort units remain distinct.", x=1000)
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
# Final terminology follows actual inputs and publication artifacts.
p = OUT / "end_to_end.json"
s = json.loads(p.read_text())
by = {n["id"]: n for n in s["nodes"]}
by["cache"].update(
    label="Main PDF + SI: paper_pool\nParsed hit: reuse\nMiss: acquire + MinerU",
    font_size=18,
)
by["finalize"].update(
    label="Finalize verified execution\nPooled estimate + uncertainty\nCode • ledger • plots • report",
    font_size=18,
    height=104,
)
by["cv0"]["label"] = "point + stat."
s["labels"][0]["text"] = "(a) End-to-end evidence synthesis"
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
p = OUT / "benchmark.json"
s = json.loads(p.read_text())
for edge in s["edges"]:
    if edge.get("label") == "native retrieval":
        edge["label"] = "declared retrieval"
p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
# Canonical sources plus root mirrors for manuscript links.
for name in ("end_to_end", "benchmark"):
    (OUT / "specs" / (name + ".json")).write_bytes(
        (OUT / (name + ".json")).read_bytes()
    )
