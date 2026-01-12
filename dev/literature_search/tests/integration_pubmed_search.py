import os
import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_sources.pubmed_client import PubMedClient
from epidemiology.utils import export_records


def run_pubmed_smoke_test(
    query: str = "theory of mind", retmax: int = 5, medline_only=True
):
    print("Integration test: PubMed search")

    email = os.getenv("NCBI_EMAIL")
    if not email:
        print("Warning: NCBI_EMAIL is not set. NCBI recommends providing an email.")

    client = PubMedClient(email=email, medline_only=medline_only)
    papers = client.search(query=query, retmax=retmax)

    out_dir = Path("./tests/data/pubmed")
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "query": query,
        "requested": retmax,
        "returned": len(papers),
    }
    outputs = export_records(
        [p.to_dict() for p in papers],
        out_dir,
        "pubmed_search_results",
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
        raise RuntimeError("PubMed search returned no results")

    # Basic sanity checks
    first = papers[0]
    assert first.title, "Expected non-empty title"
    assert first.authors is not None, "Expected authors list"


if __name__ == "__main__":
    run_pubmed_smoke_test(medline_only=False)
