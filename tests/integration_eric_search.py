import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_sources.eric_client import ERICClient
from epidemiology.utils import export_records


def run_eric_smoke_test(query: str = "learning", limit: int = 5):
    """
    Simple integration test for ERIC search and download.
    """
    print("Integration test: ERIC search")

    client = ERICClient()
    papers = client.search(query=query, limit=limit, enrich_doi=True)

    out_dir = Path("./tests/data/eric")
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "query": query,
        "requested": limit,
        "returned": len(papers),
    }
    outputs = export_records(
        [p.to_dict() for p in papers],
        out_dir,
        "eric_search_results",
        metadata=metadata,
    )

    print(f"Found {len(papers)} papers")
    for i, p in enumerate(papers, 1):
        print(f"{i}. {p.title[:120]} | {p.id} | {p.published.date()}")

    if "json" in outputs:
        print(f"Saved results to: {outputs['json']}")
    if "csv" in outputs:
        print(f"Saved CSV to: {outputs['csv']}")

    if not papers:
        raise RuntimeError("ERIC search returned no results")

    # Basic sanity checks
    first = papers[0]
    assert first.title, "Expected non-empty title"
    assert first.authors is not None, "Expected authors list"


if __name__ == "__main__":
    query = "Theory of mind"
    run_eric_smoke_test(query=query, limit=20)
