"""Streamlit dashboard for visualizing screening runs and outputs."""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
LIT_SEARCH_ROOT = APP_DIR.parent
REPO_ROOT = LIT_SEARCH_ROOT.parents[1]
sys.path.insert(0, str(LIT_SEARCH_ROOT / "src"))

from screening.dashboard_data import (
    discover_screening_runs,
    filter_papers,
    load_screened_dataframe,
    load_text_preview,
    summarize_dataframe,
)

st.set_page_config(
    page_title="MetaAgent-Epi Screening Dashboard",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
      :root {
        --bg: #f8fafc;
        --panel: rgba(255,255,255,0.9);
        --panel-soft: rgba(255,255,255,0.72);
        --stroke: #dbe3ee;
        --stroke-strong: #c7d3e1;
        --ink: #1e293b;
        --muted: #64748b;
        --blue: #3b82f6;
        --blue-soft: #60a5fa;
        --orange: #f97316;
        --green: #16a34a;
        --red: #dc2626;
        --shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
      }
      .stApp {
        font-family: 'Fira Sans', sans-serif;
        background:
          linear-gradient(180deg, rgba(59,130,246,0.04), transparent 18%),
          linear-gradient(180deg, var(--bg), #eef3f9);
        color: var(--ink);
      }
      .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
      }
      h1, h2, h3, h4 {
        font-family: 'Fira Sans', sans-serif;
        letter-spacing: -0.025em;
        color: var(--ink);
        font-weight: 600;
      }
      [data-testid="stSidebar"] {
        background: rgba(248,250,252,0.92);
        border-right: 1px solid var(--stroke);
      }
      [data-testid="stSidebar"] * {
        font-family: 'Fira Sans', sans-serif;
      }
      [data-testid="stMetricLabel"] {
        color: var(--muted);
        font-size: 0.82rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      [data-testid="stMetricValue"] {
        font-family: 'Fira Code', monospace;
        font-size: 1.55rem;
        color: var(--ink);
      }
      [data-testid="stMetric"] {
        background: var(--panel);
        border: 1px solid var(--stroke);
        border-radius: 14px;
        padding: 0.7rem 0.85rem;
        box-shadow: var(--shadow);
      }
      .hero {
        background: var(--panel);
        border: 1px solid var(--stroke);
        border-radius: 18px;
        padding: 1.1rem 1.2rem 1rem 1.2rem;
        margin-bottom: 1rem;
        box-shadow: var(--shadow);
      }
      .kicker {
        color: var(--blue);
        font-size: 0.76rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.09em;
      }
      .hero-copy {
        color: var(--muted);
        font-size: 0.96rem;
        line-height: 1.5;
      }
      .surface {
        background: var(--panel);
        border: 1px solid var(--stroke);
        border-radius: 14px;
        padding: 0.9rem 1rem;
        margin-bottom: 0.75rem;
        box-shadow: var(--shadow);
      }
      .surface.soft {
        background: var(--panel-soft);
      }
      .meta-grid {
        display: grid;
        grid-template-columns: 120px 1fr;
        gap: 0.28rem 0.85rem;
        align-items: start;
      }
      .meta-key {
        color: var(--muted);
        font-size: 0.86rem;
      }
      .meta-val {
        color: var(--ink);
        font-weight: 500;
        word-break: break-word;
      }
      .section-caption {
        color: var(--muted);
        font-size: 0.86rem;
        margin-top: -0.15rem;
        margin-bottom: 0.9rem;
      }
      .run-chip {
        display: inline-block;
        font-family: 'Fira Code', monospace;
        font-size: 0.8rem;
        color: var(--blue);
        background: rgba(59,130,246,0.08);
        border: 1px solid rgba(59,130,246,0.18);
        border-radius: 999px;
        padding: 0.22rem 0.55rem;
        margin-bottom: 0.55rem;
      }
      [data-testid="stTabs"] [role="tablist"] {
        gap: 0.4rem;
      }
      [data-testid="stTabs"] [role="tab"] {
        border-radius: 999px;
        padding: 0.3rem 0.9rem;
        border: 1px solid var(--stroke);
        background: rgba(255,255,255,0.65);
      }
      [data-testid="stTabs"] [aria-selected="true"] {
        background: rgba(59,130,246,0.09);
        border-color: rgba(59,130,246,0.28);
      }
      .stDataFrame, [data-testid="stJson"] {
        border: 1px solid var(--stroke);
        border-radius: 14px;
        overflow: hidden;
      }
      .funnel-shell {
        background: var(--panel);
        border: 1px solid var(--stroke);
        border-radius: 14px;
        padding: 0.9rem 1rem 0.45rem 1rem;
        box-shadow: var(--shadow);
      }
      code, .stCodeBlock {
        font-family: 'Fira Code', monospace;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="kicker">MetaAgent-Epi · Local Observatory</div>
          <h1 style="margin:0.2rem 0 0.35rem 0;">Screening Dashboard</h1>
          <div class="hero-copy">
            Inspect screening runs, compare routing behavior, trace full-text rescue failures,
            and audit screened outputs from local manifests without touching the workflow code.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    default_root = REPO_ROOT
    with st.sidebar:
        st.header("Run Source")
        root_input = st.text_input("Manifest search root", value=str(default_root))
        topic_filter = st.multiselect(
            "Topic filter",
            ["serial_interval", "reproduction_number", "fatality", "unknown"],
            default=[],
        )

    runs = discover_screening_runs(Path(root_input))
    if topic_filter:
        runs = [run for run in runs if run["topic"] in topic_filter]

    if not runs:
        st.warning("No screening manifests were found under the selected root.")
        return

    labels = [run["label"] for run in runs]
    selected_label = st.sidebar.selectbox("Select screening run", labels, index=0)
    run = next(item for item in runs if item["label"] == selected_label)
    df = load_screened_dataframe(run.get("screened_csv"))
    summary = summarize_dataframe(df)

    _render_overview(run, summary)

    tab_overview, tab_papers, tab_files = st.tabs(
        ["Overview", "Paper Table", "Files & Provenance"]
    )
    with tab_overview:
        _render_charts(summary)
        _render_runtime(run)
    with tab_papers:
        _render_papers(df)
    with tab_files:
        _render_files(run)


def _render_overview(run: dict, summary: dict) -> None:
    extra = run.get("extra") or {}
    st.markdown(
        f'<div class="run-chip">{run.get("topic", "unknown")} · {run.get("config") or "legacy"}</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(6)
    cols[0].metric("Pool", summary["pool"])
    cols[1].metric("GT in Pool", summary["gt_in_pool"])
    cols[2].metric("Strong", int(extra.get("strong_count", 0)))
    cols[3].metric("Possible", int(extra.get("possible_count", 0)))
    cols[4].metric("Unlikely", int(extra.get("unlikely_count", 0)))
    cols[5].metric("Full-text Errors", int(extra.get("fulltext_error_count", 0)))

    info_col, meta_col = st.columns([1.35, 1])
    with info_col:
        st.subheader("Run Summary")
        st.markdown(
            '<div class="section-caption">Local run identity, selected output, and routing context.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="surface">
              <div class="meta-grid">
                <div class="meta-key">Topic</div><div class="meta-val">{run.get('topic')}</div>
                <div class="meta-key">Config</div><div class="meta-val">{run.get('config') or '-'}</div>
                <div class="meta-key">Timestamp</div><div class="meta-val">{run.get('timestamp_utc') or '-'}</div>
                <div class="meta-key">Output</div><div class="meta-val">{Path(run.get('screened_csv')).name if run.get('screened_csv') else 'N/A'}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Screening Flow")
    st.markdown(
        '<div class="section-caption">Compact funnel-style stage view from pool to predicted relevant papers.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="funnel-shell">', unsafe_allow_html=True)
    funnel_df = _build_funnel_df(summary)
    st.altair_chart(_build_funnel_chart(funnel_df), width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)
    with meta_col:
        st.subheader("Git Snapshot")
        st.markdown(
            '<div class="section-caption">Provenance state captured with the run.</div>',
            unsafe_allow_html=True,
        )
        git = run.get("git") or {}
        st.markdown(
            f"""
            <div class="surface soft">
              <div class="meta-grid">
                <div class="meta-key">Branch</div><div class="meta-val">{git.get('branch') or '-'}</div>
                <div class="meta-key">Commit</div><div class="meta-val">{(git.get('commit') or '-')[:12]}</div>
                <div class="meta-key">Dirty</div><div class="meta-val">{git.get('dirty')}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_charts(summary: dict) -> None:
    chart_cols = st.columns(3)
    chart_specs = [
        ("Decision Mix", summary["decision_counts"], "#925EB0"),
        ("Screening Stages", summary["stage_counts"], "#7E99F4"),
        ("Full-text Status", summary["fulltext_counts"], "#7AB656"),
    ]
    for col, (title, series, color) in zip(chart_cols, chart_specs):
        with col:
            st.subheader(title)
            st.markdown(
                '<div class="section-caption">Compact count view for the selected run.</div>',
                unsafe_allow_html=True,
            )
            if series.empty:
                st.info("No data")
                continue
            chart_df = (
                series.rename_axis("label")
                .reset_index(name="count")
                .sort_values("count", ascending=True)
            )
            st.altair_chart(
                _build_horizontal_bar_chart(chart_df, color=color),
                width="stretch",
            )


def _render_runtime(run: dict) -> None:
    st.subheader("Runtime Snapshot")
    st.markdown(
        '<div class="section-caption">Captured provider configuration from the manifest.</div>',
        unsafe_allow_html=True,
    )
    runtime = run.get("runtime") or {}
    llm = runtime.get("llm") or {}
    mineru = runtime.get("mineru") or {}
    left, right = st.columns(2)
    with left:
        st.json({"llm": llm}, expanded=False)
    with right:
        st.json({"mineru": mineru}, expanded=False)


def _render_papers(df: pd.DataFrame) -> None:
    st.subheader("Paper Table")
    st.markdown(
        '<div class="section-caption">Filter decisions and inspect paper-level screening outcomes.</div>',
        unsafe_allow_html=True,
    )
    if df.empty:
        st.info("No screened CSV is available for this run.")
        return

    filter_cols = st.columns([1.2, 0.9, 1.6])
    suggestions = []
    with filter_cols[0]:
        if "llm_suggest" in df.columns:
            suggestions = st.multiselect(
                "Decision filter",
                sorted(df["llm_suggest"].dropna().unique().tolist()),
                default=[],
            )
    with filter_cols[1]:
        only_gt = st.checkbox("Only GT", value=False)
    with filter_cols[2]:
        query = st.text_input("Search PMID / Title", value="")
    filtered = filter_papers(df, suggestions=suggestions, only_gt=only_gt, query=query)
    preferred_columns = [
        "PMID",
        "is_ground_truth",
        "Title",
        "llm_suggest",
        "overall_score",
        "screening_stage",
        "fulltext_status",
        "overall_justification",
    ]
    visible_columns = [col for col in preferred_columns if col in filtered.columns]
    st.caption(f"{len(filtered)} papers shown")
    display_df = filtered[visible_columns].copy() if visible_columns else filtered.copy()
    styler = _style_paper_table(display_df)
    st.dataframe(styler, width="stretch", hide_index=True)


def _render_files(run: dict) -> None:
    st.subheader("Files & Provenance")
    st.markdown(
        '<div class="section-caption">Trace exact inputs, outputs, manifest path, and report preview.</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Inputs**")
        st.json(run.get("inputs") or [], expanded=False)
        st.markdown("**Outputs**")
        st.json(run.get("outputs") or [], expanded=False)
    with right:
        st.markdown("**Manifest**")
        st.code(run.get("manifest_path") or "-", language="text")
        st.markdown("**Report Preview**")
        preview = load_text_preview(run.get("report_path"))
        if preview:
            st.text(preview)
        else:
            st.info("No report preview available.")


def _build_horizontal_bar_chart(chart_df: pd.DataFrame, color: str) -> alt.Chart:
    return (
        alt.Chart(chart_df)
        .mark_bar(size=18, cornerRadiusEnd=5, color=color)
        .encode(
            x=alt.X("count:Q", title=None, axis=alt.Axis(grid=True, tickCount=4)),
            y=alt.Y("label:N", title=None, sort=None, axis=alt.Axis(labelLimit=170)),
            tooltip=["label:N", "count:Q"],
        )
        .properties(height=max(180, 34 * len(chart_df)))
    )


def _build_funnel_df(summary: dict) -> pd.DataFrame:
    stage_counts = summary.get("stage_counts", pd.Series(dtype="int64"))
    decision_counts = summary.get("decision_counts", pd.Series(dtype="int64"))
    return pd.DataFrame(
        [
            {"stage": "Pool", "count": int(summary.get("pool", 0)), "color": "#A5AEB7"},
            {
                "stage": "Title + Abstract",
                "count": int(stage_counts.get("title_abstract", 0)),
                "color": "#7E99F4",
            },
            {
                "stage": "Title Only",
                "count": int(stage_counts.get("title_only", 0)),
                "color": "#60A5FA",
            },
            {
                "stage": "Full-text",
                "count": int(stage_counts.get("full_text", 0)),
                "color": "#7AB656",
            },
            {
                "stage": "Relevant (S+P)",
                "count": int(decision_counts.get("strong_candidate", 0))
                + int(decision_counts.get("possible_candidate", 0)),
                "color": "#F97316",
            },
        ]
    )


def _build_funnel_chart(chart_df: pd.DataFrame) -> alt.Chart:
    order = chart_df["stage"].tolist()
    base = (
        alt.Chart(chart_df)
        .encode(
            y=alt.Y("stage:N", sort=order, title=None, axis=alt.Axis(labelLimit=180)),
            x=alt.X("count:Q", title=None, axis=alt.Axis(grid=True, tickCount=4)),
        )
        .properties(height=240)
    )
    bars = base.mark_bar(size=18, cornerRadiusEnd=6).encode(
        color=alt.Color("color:N", scale=None, legend=None),
        tooltip=["stage:N", "count:Q"],
    )
    labels = base.mark_text(
        align="left",
        baseline="middle",
        dx=8,
        color="#1E293B",
        font="Fira Code",
        fontSize=12,
    ).encode(text="count:Q")
    return bars + labels


def _style_paper_table(df: pd.DataFrame):
    if df.empty:
        return df.style

    styled = df.copy()
    if "llm_suggest" in styled.columns:
        styled["llm_suggest"] = styled["llm_suggest"].replace(
            {
                "strong_candidate": "Strong",
                "possible_candidate": "Possible",
                "unlikely_candidate": "Unlikely",
                "error": "Error",
                "needs_full_text": "Needs Full Text",
            }
        )
    if "is_ground_truth" in styled.columns:
        styled["is_ground_truth"] = styled["is_ground_truth"].replace({"✓": "GT"})

    def badge_style(value: object, kind: str) -> str:
        token = str(value).strip()
        if not token:
            return ""
        color_map = {
            ("llm_suggest", "Strong"): ("#ecfdf3", "#16a34a"),
            ("llm_suggest", "Possible"): ("#fff7ed", "#f97316"),
            ("llm_suggest", "Unlikely"): ("#eef2ff", "#6366f1"),
            ("llm_suggest", "Error"): ("#fef2f2", "#dc2626"),
            ("llm_suggest", "Needs Full Text"): ("#eff6ff", "#2563eb"),
            ("fulltext_status", "screened"): ("#ecfdf3", "#15803d"),
            ("fulltext_status", "converted"): ("#eff6ff", "#2563eb"),
            ("fulltext_status", "pending"): ("#fff7ed", "#c2410c"),
            ("fulltext_status", "download_failed"): ("#fef2f2", "#dc2626"),
            ("fulltext_status", "conversion_failed"): ("#fef2f2", "#dc2626"),
            ("fulltext_status", "read_failed"): ("#fef2f2", "#dc2626"),
            ("is_ground_truth", "GT"): ("#ecfeff", "#0f766e"),
        }
        bg, fg = color_map.get((kind, token), ("#f8fafc", "#475569"))
        return (
            f"background-color: {bg}; color: {fg}; font-weight: 600; "
            "border-radius: 999px; padding: 0.18rem 0.48rem; text-align: center;"
        )

    styler = (
        styled.style.hide(axis="index")
        .set_properties(
            subset=[col for col in styled.columns if col not in {"llm_suggest", "fulltext_status", "is_ground_truth"}],
            **{"font-size": "0.92rem"},
        )
        .set_properties(subset=[col for col in styled.columns if col == "Title"], **{"min-width": "360px"})
    )
    for col in ["llm_suggest", "fulltext_status", "is_ground_truth"]:
        if col in styled.columns:
            styler = styler.map(lambda v, kind=col: badge_style(v, kind), subset=[col])
    return styler


if __name__ == "__main__":
    main()
