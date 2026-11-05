# Method figures

Local **FigureSpec → editable SVG**, exported to PDF and PNG. These diagrams describe implementation and evidence boundaries, not measured performance or a claim that scientific benchmarks pass. No model call, network request or new experiment was used.

| Figure | Editable SVG | PDF / PNG | FigureSpec |
|---|---|---|---|
| End-to-end evidence synthesis | [end_to_end.svg](end_to_end.svg) | [PDF](end_to_end.pdf) · [PNG](end_to_end.png) | [end_to_end.json](end_to_end.json) |
| Benchmark construction / evaluation | [benchmark.svg](benchmark.svg) | [PDF](benchmark.pdf) · [PNG](benchmark.png) | [benchmark.json](benchmark.json) |

Canonical JSON also resides in[specs/](specs/); root JSON mirrors the same bytes for manuscript links. [build_specs.py](build_specs.py) reproduces the layouts. Edit the generator/specification, not generated SVG. Labels remain native text, paths and shapes, with no raster figure embedded. Font fallback: Noto Sans, DejaVu Sans, sans-serif.

## Captions

**Figure1. End-to-end evidence synthesis and independently callable modules.** Shared research context connects query/retrieval, Screening, default full Coding A+B, and Pi Synthesis. Verified paper_pool parsed-cache hits are reused; misses follow PDF/SI acquisition and MinerU parsing. TA S/P or needs-full-text can proceed to FT; FT retained records with screened status may proceed to Coding, while unresolved eligibility/source states remain pending for repair/review/resume. Coding extracts candidates and finalizes source-bound fields with evidence and review flags. Pi inspects the table/sources, commits a common-estimand plan, writes code, runs sandbox execution/validation and finalizes verified artifacts. Feedback is bounded. Execution success is distinct from scientific validity. Whole method documents may contain original-SR results.

**Figure2. Source-grounded benchmark construction and layered evaluation.** Original SR material supports membership, identity/version resolution and offline reference snapshots. Declared retrieval produces raw_search; manually rescued records remain separately identified before creation of versioned pool views. Model input projection supplies task/metadata/documents; structured reference-label tables are reserved for offline comparison. Evaluation preserves distinct denominators and separates retrieval/screening, Coding field/evidence support, and Synthesis execution/math, scientific correctness and original-SR reproduction. Historical nonmembership is not independently verified scientific ineligibility. Report, estimate and cohort units are distinct. Mutable counts and claims of historical search-index replication are omitted.

## Reproduce

From repository root, with the installed figure-spec skill:

```bash
.venv/bin/python docs/figures/methods/build_specs.py
.venv/bin/python /home/yanhaoyang/.agents/skills/figure-spec/scripts/figure_renderer.py validate docs/figures/methods/specs/end_to_end.json
.venv/bin/python /home/yanhaoyang/.agents/skills/figure-spec/scripts/figure_renderer.py validate docs/figures/methods/specs/benchmark.json
.venv/bin/python /home/yanhaoyang/.agents/skills/figure-spec/scripts/figure_renderer.py render docs/figures/methods/specs/end_to_end.json --output docs/figures/methods/end_to_end.svg
.venv/bin/python /home/yanhaoyang/.agents/skills/figure-spec/scripts/figure_renderer.py render docs/figures/methods/specs/benchmark.json --output docs/figures/methods/benchmark.svg
rsvg-convert -f pdf docs/figures/methods/end_to_end.svg -o docs/figures/methods/end_to_end.pdf
rsvg-convert -f png docs/figures/methods/end_to_end.svg -o docs/figures/methods/end_to_end.png
rsvg-convert -f pdf docs/figures/methods/benchmark.svg -o docs/figures/methods/benchmark.pdf
rsvg-convert -f png docs/figures/methods/benchmark.svg -o docs/figures/methods/benchmark.png
```

On this host rsvg-convert is`/home/yanhaoyang/envs/ffmpeg/bin/rsvg-convert`. SVG bytes are deterministic for fixed renderer/spec/fonts; PDF metadata may be tool-version dependent. No cross-model review was invoked. Rendered PNGs were visually inspected; layout checks and source hashes are recorded in`layout-checks.json` and`SOURCE_BINDINGS.json`.

## Visibility and scope

Reference tables not being directly injected does **not** guarantee answer-free source documents. Current Pi stages complete source text/original files; evidence tools and generated code can read authorized contents, including an original SR pooled estimate. Prompt prohibitions are behavioral safeguards, not semantic redaction. See [METHOD_IMPLEMENTATION_MAP.md](../../design/METHOD_IMPLEMENTATION_MAP.md).

New all22-task construction and earlier actual single/batch experiments bind different manifests. Counts/results belong to their own snapshots, not these diagrams. Historical membership, source identity, independent scientific eligibility and target-analysis contributions remain different layers; no human-gold or full-completeness claim is implied.
