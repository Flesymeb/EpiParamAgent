"""Forest plots rendered only from deterministic numeric artifact rows."""
from __future__ import annotations

from pathlib import Path


def write_forest_plot(result, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = result["forest_data"]
    # Keep readable plots bounded. The JSONL contains the complete forest data.
    visible = rows[:80]
    fig, ax = plt.subplots(figsize=(9, max(3, .28 * (len(visible) + 3))))
    for i, row in enumerate(visible):
        point, low, high = row["point_estimate"], row.get("ci_lower"), row.get("ci_upper")
        if low is not None and high is not None:
            ax.plot([low, high], [i, i], color="#54718b", linewidth=1)
        ax.scatter([point], [i], s=25 + 150 * row["weight"], marker="s", color="#274c77")
    summary = result["result"]
    ax.axvline(summary["pooled_mean"], color="#bb3e03", linestyle="--", label="Synthesis estimate")
    ax.set_yticks(range(len(visible)), [r["estimate_id"] for r in visible])
    ax.invert_yaxis()
    ax.set_xlabel(summary["unit"])
    suffix = f" (first {len(visible)} of {len(rows)}; full data in study_weights.jsonl)" if len(rows) > len(visible) else ""
    ax.set_title(str(result["analysis_id"]) + suffix)
    if "tau2" in summary:
        ax.text(.01,-.16,f"Q={summary.get('Q',0):.3g}; I²={summary.get('i2',0):.3g}%; τ²={summary['tau2']:.3g}; {summary.get('analysis_scale','original')} scale",transform=ax.transAxes,fontsize=9)
    ax.legend(loc="best")
    fig.tight_layout()
    paths = {}
    for ext in ("png", "pdf"):
        path = Path(output_dir) / ("forest." + ext)
        fig.savefig(path, dpi=160)
        paths["forest_" + ext] = path
    plt.close(fig)
    return paths


def write_diagnostic_plots(result, output_dir):
    """Render source-bound LOO and funnel artifacts with stale-output cleanup."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(output_dir);paths={}
    loo=[r for r in result.get('influence_diagnostics',{}).get('rows',[]) if r.get('status')=='computed']
    if not loo:
        loo=[{'estimate_id':r['name'].removeprefix('leave_one_out:'),'leave_one_out_estimate':r['result']['pooled_mean'],
              'ci_lower':r['result'].get('ci_lower'),'ci_upper':r['result'].get('ci_upper')}
             for r in result.get('sensitivity_results',[]) if r['name'].startswith('leave_one_out:') and r.get('result')]
    funnel=result.get('publication_bias',{}).get('funnel_data',[])
    for name in ('leave_one_out','funnel'):
        if not (loo if name=='leave_one_out' else funnel):
            for ext in ('png','pdf'):(root/(name+'.'+ext)).unlink(missing_ok=True)
            continue
        fig,ax=plt.subplots(figsize=(8, max(3,min(12,.3*len(loo)))) if name=='leave_one_out' else (7,5))
        if name=='leave_one_out':
            visible=loo[:80]
            for i,row in enumerate(visible):
                low,high=row.get('ci_lower'),row.get('ci_upper')
                if low is not None and high is not None:ax.plot([low,high],[i,i],color='#54718b')
                ax.scatter([row['leave_one_out_estimate']],[i],color='#274c77')
            ax.set_yticks(range(len(visible)),[r['estimate_id'] for r in visible]);ax.invert_yaxis()
            if result.get('result'):ax.axvline(result['result']['pooled_mean'],linestyle='--',color='#bb3e03')
            ax.set_title('Leave one independent estimate out'+(' (first 80; full JSON available)' if len(loo)>80 else ''))
            ax.set_xlabel(result.get('result',{}).get('unit','Estimate'))
        else:
            ax.scatter([r['effect'] for r in funnel],[r['se'] for r in funnel],color='#274c77')
            ax.invert_yaxis();ax.set_xlabel('Effect on declared analysis scale');ax.set_ylabel('Reported/derived SE')
            ax.set_title('Funnel diagnostic: asymmetry is not proof of publication bias')
        fig.tight_layout()
        for ext in ('png','pdf'):
            path=root/(name+'.'+ext);fig.savefig(path,dpi=160);paths[name+'_'+ext]=path
        plt.close(fig)
    return paths
