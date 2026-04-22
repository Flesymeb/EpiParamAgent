"""Rare disease PubMed batch search and metadata download.

For each disease in disease_list.yaml, searches PubMed independently,
saves per-disease results under:

    dataset/rare_disease/batch_{YYYYMMDD}/
        {disease_id}-{Disease_Name}/
            pmids.csv        – PMID list with rank and search metadata
            metadata.csv     – enriched per-paper metadata

Usage
-----
# Full batch (all diseases in disease_list.yaml):
python dataset/scripts/pubmed_search_rare_disease.py

# Single disease by id:
python dataset/scripts/pubmed_search_rare_disease.py --disease-id RD001

# Custom output batch name:
python dataset/scripts/pubmed_search_rare_disease.py --batch my_batch

# Limit results per disease:
python dataset/scripts/pubmed_search_rare_disease.py --retmax 200

# Only fetch PMIDs (skip metadata enrichment):
python dataset/scripts/pubmed_search_rare_disease.py --pmids-only

Run from repo root (uses workspace venv):
    uv run --directory dev python dataset/scripts/pubmed_search_rare_disease.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
RARE_DISEASE_DIR = DATASET_DIR / "rare_disease"
DISEASE_LIST_FILE = RARE_DISEASE_DIR / "disease_list.yaml"

# Reuse existing PubMedClient from literature_search
_LIT_SEARCH_SRC = REPO_ROOT / "dev" / "literature_search" / "src"
_TOOLS_SRC = REPO_ROOT / "dev" / "tools"
for _p in (_LIT_SEARCH_SRC, _TOOLS_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from data_sources.pubmed_client import PubMedClient  # type: ignore
    _HAVE_CLIENT = True
except ImportError:
    _HAVE_CLIENT = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata fields
# ---------------------------------------------------------------------------
PMID_FIELDS = ["rank", "pmid", "disease_id", "disease_name", "search_query", "search_date", "total_results"]
META_FIELDS = [
    "pmid", "disease_id", "disease_name",
    "title", "abstract", "authors", "journal", "year", "doi", "pmcid", "mesh_terms",
]


# ---------------------------------------------------------------------------
# Extended fetch: PMID + MeSH + PMCID
# ---------------------------------------------------------------------------

def _safe_text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return ET.tostring(elem, encoding="unicode", method="text").strip()


def fetch_extended_metadata(
    pmids: List[str],
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    verify_ssl: bool = True,
    batch_size: int = 100,
    sleep_between: float = 0.35,
) -> Dict[str, Dict[str, Any]]:
    """Fetch title/abstract/authors/journal/year/doi/pmcid/mesh for a list of PMIDs.

    Returns dict keyed by pmid.
    """
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params_base: Dict[str, str] = {"db": "pubmed", "retmode": "xml"}
    if api_key:
        params_base["api_key"] = api_key
    if email:
        params_base["email"] = email

    results: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(pmids), batch_size):
        chunk = pmids[i : i + batch_size]
        params = {**params_base, "id": ",".join(chunk)}
        try:
            resp = requests.get(base, params=params, timeout=30, verify=verify_ssl)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception as exc:
            logger.warning("efetch failed for chunk starting at %s: %s", chunk[0], exc)
            continue

        for article in root.findall(".//PubmedArticle"):
            try:
                pmid = _safe_text(article.find(".//PMID"))
                if not pmid:
                    continue

                title = _safe_text(article.find(".//ArticleTitle"))

                # Abstract (may have multiple AbstractText sections)
                abstract_parts = article.findall(".//AbstractText")
                abstract = " ".join(
                    (_safe_text(p) for p in abstract_parts if _safe_text(p))
                )

                # Authors
                authors = []
                for auth in article.findall(".//Author"):
                    last = _safe_text(auth.find("LastName"))
                    fore = _safe_text(auth.find("ForeName"))
                    name = f"{last}, {fore}".strip(", ")
                    if name:
                        authors.append(name)

                journal = _safe_text(article.find(".//Journal/Title"))

                # Publication year
                year = ""
                for year_tag in ("PubDate/Year", "PubDate/MedlineDate"):
                    y = article.find(f".//{year_tag}")
                    if y is not None:
                        year = _safe_text(y)[:4]
                        break

                # DOI
                doi = ""
                for aid in article.findall(".//ArticleId"):
                    if aid.get("IdType") == "doi":
                        doi = _safe_text(aid)
                        break

                # PMCID
                pmcid = ""
                for aid in article.findall(".//ArticleId"):
                    if aid.get("IdType") == "pmc":
                        pmcid = _safe_text(aid)
                        break

                # MeSH headings
                mesh = []
                for mh in article.findall(".//MeshHeading"):
                    desc = mh.find("DescriptorName")
                    if desc is not None:
                        mesh.append(_safe_text(desc))

                results[pmid] = {
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "authors": "; ".join(authors),
                    "journal": journal,
                    "year": year,
                    "doi": doi,
                    "pmcid": pmcid,
                    "mesh_terms": "; ".join(mesh),
                }
            except Exception as exc:
                logger.warning("Failed parsing article: %s", exc)

        if i + batch_size < len(pmids):
            time.sleep(sleep_between)

    return results


# ---------------------------------------------------------------------------
# Disease-level search
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Convert disease name to filesystem-safe slug."""
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def search_disease(
    disease: Dict[str, str],
    retmax: int,
    client: Optional["PubMedClient"],
    api_key: Optional[str],
    email: Optional[str],
    verify_ssl: bool,
) -> List[str]:
    """Return list of PMIDs for a single disease query."""
    query = disease.get("query") or disease["english_name"]
    logger.info("[%s] Searching: %s (retmax=%d)", disease["id"], query, retmax)

    if client is not None:
        papers = client.search(query, retmax=retmax)
        client.last_total  # side-effect only
        pmids = [p.id.replace("pubmed:", "") for p in papers if p.id]
        logger.info("[%s] Found %d PMIDs via PubMedClient", disease["id"], len(pmids))
        return pmids

    # Fallback: direct esearch
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params: Dict[str, Any] = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email

    try:
        resp = requests.get(url, params=params, timeout=30, verify=verify_ssl)
        resp.raise_for_status()
        data = resp.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "?")
        logger.info("[%s] Found %s total, returning %d", disease["id"], total, len(pmids))
        return pmids
    except Exception as exc:
        logger.error("[%s] Search failed: %s", disease["id"], exc)
        return []


def process_disease(
    disease: Dict[str, str],
    batch_dir: Path,
    retmax: int,
    pmids_only: bool,
    client: Optional["PubMedClient"],
    api_key: Optional[str],
    email: Optional[str],
    verify_ssl: bool,
) -> None:
    """Search PubMed for one disease and save pmids.csv + metadata.csv."""
    disease_id = disease["id"]
    name = disease["english_name"]
    query = disease.get("query") or name
    slug = _slug(name)
    out_dir = batch_dir / f"{disease_id}-{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    search_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Search
    pmids = search_disease(disease, retmax, client, api_key, email, verify_ssl)

    # 2. Write pmids.csv
    pmids_path = out_dir / "pmids.csv"
    with open(pmids_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PMID_FIELDS)
        writer.writeheader()
        for rank, pmid in enumerate(pmids, 1):
            writer.writerow({
                "rank": rank,
                "pmid": pmid,
                "disease_id": disease_id,
                "disease_name": name,
                "search_query": query,
                "search_date": search_date,
                "total_results": len(pmids),
            })
    logger.info("[%s] Saved %d PMIDs → %s", disease_id, len(pmids), pmids_path)

    if pmids_only or not pmids:
        return

    # 3. Fetch extended metadata
    logger.info("[%s] Fetching metadata for %d papers ...", disease_id, len(pmids))
    meta = fetch_extended_metadata(
        pmids, api_key=api_key, email=email, verify_ssl=verify_ssl
    )

    # 4. Write metadata.csv
    meta_path = out_dir / "metadata.csv"
    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=META_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for pmid in pmids:
            row = meta.get(pmid, {"pmid": pmid})
            row["disease_id"] = disease_id
            row["disease_name"] = name
            writer.writerow(row)
    logger.info("[%s] Saved metadata → %s", disease_id, meta_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-disease PubMed search and metadata download for rare diseases."
    )
    parser.add_argument(
        "--disease-list",
        default=str(DISEASE_LIST_FILE),
        help="Path to disease_list.yaml (default: dataset/rare_disease/disease_list.yaml)",
    )
    parser.add_argument(
        "--disease-id",
        default=None,
        help="Process only this disease ID (e.g. RD001). Default: all.",
    )
    parser.add_argument(
        "--batch",
        default=None,
        help="Batch directory name under dataset/rare_disease/. Default: batch_YYYYMMDD.",
    )
    parser.add_argument(
        "--retmax",
        type=int,
        default=500,
        help="Max results per disease (default: 500).",
    )
    parser.add_argument(
        "--pmids-only",
        action="store_true",
        help="Only fetch PMIDs; skip metadata enrichment.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override base output directory (default: dataset/rare_disease/).",
    )
    args = parser.parse_args()

    # Load env
    try:
        from common.config import load_runtime_env  # type: ignore
        load_runtime_env("literature_search")
    except Exception:
        pass

    api_key = os.getenv("NCBI_API_KEY") or os.getenv("PUBMED_API_KEY")
    email = os.getenv("NCBI_EMAIL")
    verify_ssl = os.getenv("NCBI_VERIFY_SSL", "true").lower() != "false"

    # Load disease list
    disease_list_path = Path(args.disease_list)
    if not disease_list_path.exists():
        logger.error("Disease list not found: %s", disease_list_path)
        sys.exit(1)

    with open(disease_list_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    diseases: List[Dict[str, str]] = config.get("diseases", [])

    if args.disease_id:
        diseases = [d for d in diseases if d["id"] == args.disease_id]
        if not diseases:
            logger.error("Disease ID not found: %s", args.disease_id)
            sys.exit(1)

    # Batch directory
    base_dir = Path(args.output_dir) if args.output_dir else RARE_DISEASE_DIR
    batch_name = args.batch or f"batch_{datetime.now().strftime('%Y%m%d')}"
    batch_dir = base_dir / batch_name
    batch_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output batch: %s", batch_dir)

    # PubMedClient
    client: Optional["PubMedClient"] = None
    if _HAVE_CLIENT:
        try:
            client = PubMedClient(api_key=api_key, email=email)
        except Exception as exc:
            logger.warning("PubMedClient init failed (%s), using direct requests.", exc)

    # Process each disease
    for disease in diseases:
        try:
            process_disease(
                disease=disease,
                batch_dir=batch_dir,
                retmax=args.retmax,
                pmids_only=args.pmids_only,
                client=client,
                api_key=api_key,
                email=email,
                verify_ssl=verify_ssl,
            )
        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", disease["id"], exc)

    logger.info("Done. Results under: %s", batch_dir)


if __name__ == "__main__":
    main()
