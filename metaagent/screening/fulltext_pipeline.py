"""Full-text preparation pipeline for screening papers without abstracts."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Any

from metaagent.config import load_mineru_config

BASE_DIR = Path(__file__).resolve().parents[2]
FULLTEXT_CACHE_ROOT = BASE_DIR.parent / "paper_pool"
PDF_CACHE_DIR = FULLTEXT_CACHE_ROOT / "pdfs"
MD_CACHE_DIR = FULLTEXT_CACHE_ROOT / "markdown"


def ensure_fulltext_cache_dirs() -> None:
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MD_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_pdf_fetcher_module():
    paper_fetch_dir = BASE_DIR.parent / "tools" / "paper_fetch"
    if str(paper_fetch_dir) not in sys.path:
        sys.path.insert(0, str(paper_fetch_dir))
    import pdf_fetcher as pdf_fetcher

    return pdf_fetcher


def download_pdfs_batch(
    pmids: list[str],
    pmid_overrides: dict[str, dict[str, str]] | None = None,
    *,
    source_strategy: str = "pmc_first",
) -> dict[str, dict[str, str]]:
    """Download PDFs into the shared cache and return per-PMID status."""
    ensure_fulltext_cache_dirs()
    results: dict[str, dict[str, str]] = {}
    pmid_overrides = pmid_overrides or {}
    todo_pmids: list[str] = []

    for pmid in pmids:
        pmid = (pmid or "").strip()
        if not pmid:
            continue
        target_pdf = PDF_CACHE_DIR / f"PMID_{pmid}.pdf"
        if target_pdf.exists():
            print(f"[PDF] PMID_{pmid} cache hit: {target_pdf}")
            results[pmid] = {"status": "downloaded", "pdf_path": str(target_pdf)}
            continue
        todo_pmids.append(pmid)

    if not todo_pmids:
        return results

    pdf_fetcher = load_pdf_fetcher_module()
    extractor = pdf_fetcher.SciHubUrlExtractor()
    if source_strategy != "pmc_only":
        extractor.get_mirrors()

    for pmid in todo_pmids:
        target_pdf = PDF_CACHE_DIR / f"PMID_{pmid}.pdf"
        override = pmid_overrides.get(pmid, {})
        doi = (override.get("doi") or "").strip()
        pmcid_raw = (override.get("pmcid") or "").strip()
        pmcid = _normalize_pmcid(pmcid_raw)
        resolved_doi = ""
        resolved_pmcid = ""

        if not pmcid or not doi:
            resolved_doi, resolved_pmcid = extractor._resolve_pmid(pmid)
            doi = doi or resolved_doi
            pmcid = pmcid or _normalize_pmcid(resolved_pmcid)

        if pmcid_raw and pmcid_raw != pmcid:
            print(f"  [PMCID] normalized: {pmcid_raw} -> {pmcid}")
        if resolved_pmcid and not pmcid_raw:
            print(f"  [PMCID] resolved from PMID: {resolved_pmcid}")
        if not doi and not pmcid:
            results[pmid] = {"status": "no_id", "pdf_path": ""}
            continue

        print(
            f"Resolving PMID: {pmid} | DOI: {doi or 'N/A'} | PMCID: {pmcid or 'N/A'}"
        )
        if source_strategy == "pmc_only":
            print("  Full-text fetch (PMC only):")
            if not pmcid:
                results[pmid] = {"status": "pmc_unavailable", "pdf_path": ""}
                continue
            url_results = extractor._process_pmcid(pmcid, PDF_CACHE_DIR)
        else:
            print("  Full-text fetch (PMC first, Sci-Hub fallback):")
            url_results, doi, pmcid = extractor.process_pmid(
                pmid,
                download_dir=PDF_CACHE_DIR,
                doi_override=doi,
                pmcid_override=pmcid,
                prefer_pmc=True,
                allow_interactive=False,
            )
        pdf_path = _first_downloaded_pdf(url_results)
        if pdf_path and pdf_path.exists():
            if pdf_path != target_pdf:
                if target_pdf.exists():
                    try:
                        pdf_path.unlink()
                    except Exception:
                        pass
                else:
                    try:
                        pdf_path.replace(target_pdf)
                    except Exception:
                        shutil.copyfile(pdf_path, target_pdf)
            results[pmid] = {"status": "downloaded", "pdf_path": str(target_pdf)}
        else:
            results[pmid] = {
                "status": "pmc_unavailable" if source_strategy == "pmc_only" else "download_failed",
                "pdf_path": "",
            }

    missing = [pmid for pmid, info in results.items() if info["status"] != "downloaded"]
    if missing and sys.stdin.isatty():
        print(f"⚠️  {len(missing)} PDFs still not downloaded. Manually download to {PDF_CACHE_DIR} to continue.")
        try:
            user_input = input("⏸ Press Enter to re-scan cache, or type skip: ").strip().lower()
        except EOFError:
            user_input = "skip"
        if user_input != "skip":
            for pmid in missing:
                target_pdf = PDF_CACHE_DIR / f"PMID_{pmid}.pdf"
                if target_pdf.exists():
                    print(f"[PDF] PMID_{pmid} cache hit: {target_pdf}")
                    results[pmid] = {"status": "downloaded", "pdf_path": str(target_pdf)}
    return results


def convert_pdfs_to_markdown(
    pmid_to_pdf: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Convert cached PDFs to Markdown using MinerU."""
    ensure_fulltext_cache_dirs()
    cfg = load_mineru_config(module_hint="literature_search")
    if not cfg.api_key:
        print("⚠️  MinerU API key missing; skipping full-text conversion.")
        return {
            pmid: {"status": "conversion_failed", "md_path": "", "error": "no_api_key"}
            for pmid in pmid_to_pdf.keys()
        }

    from metaagent.pdf_reader_mineru import extract_pdf_markdown_mineru

    total_pdfs = sum(1 for info in pmid_to_pdf.values() if info.get("pdf_path"))
    if total_pdfs:
        print(f"Starting full-text conversion (MinerU): {total_pdfs}  papers | 输出目录: {MD_CACHE_DIR}")

    results: dict[str, dict[str, str]] = {}
    converted = 0
    failed = 0
    cached = 0

    for pmid, info in pmid_to_pdf.items():
        pdf_path = info.get("pdf_path") or ""
        if not pdf_path:
            failed += 1
            results[pmid] = {"status": "conversion_failed", "md_path": ""}
            continue

        paper_dir = MD_CACHE_DIR / f"PMID_{pmid}"
        md_path = paper_dir / f"PMID_{pmid}.md"
        if md_path.exists() and md_path.stat().st_size > 0:
            results[pmid] = {"status": "converted", "md_path": str(md_path)}
            converted += 1
            cached += 1
            continue

        try:
            paper_dir.mkdir(parents=True, exist_ok=True)
            print(f"  [MinerU] Converting PMID {pmid} ...")
            extracted = extract_pdf_markdown_mineru(Path(pdf_path), output_dir=paper_dir)
            if extracted.markdown:
                md_path.write_text(extracted.markdown, encoding="utf-8")
                results[pmid] = {"status": "converted", "md_path": str(md_path)}
                converted += 1
                print(f"  [MinerU] Completed PMID {pmid}")
            else:
                failed += 1
                results[pmid] = {
                    "status": "conversion_failed",
                    "md_path": "",
                    "error": "empty_markdown",
                }
                if not any(paper_dir.iterdir()):
                    paper_dir.rmdir()
        except Exception as exc:
            failed += 1
            results[pmid] = {
                "status": "conversion_failed",
                "md_path": "",
                "error": str(exc)[:200],
            }
            print(f"  [MinerU] Failed PMID {pmid}: {str(exc)[:200]}")
            if paper_dir.exists() and not any(paper_dir.iterdir()):
                paper_dir.rmdir()

    if total_pdfs:
        print(f"Full-text conversion complete: success {converted} (cached {cached}) | failed {failed}")
    return results


def prepare_fulltext_candidates(
    papers_without_abstract: list[dict[str, Any]],
    fulltext_cached: list[dict[str, Any]],
    fulltext_errors: list[dict[str, str]],
    *,
    source_strategy: str = "pmc_first",
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Prepare markdown-backed papers for full-text screening."""
    total_fulltext = len({id(p) for p in papers_without_abstract + fulltext_cached})
    print(f"\nStarting full-text screening pipeline ({total_fulltext} 篇)...")
    ensure_fulltext_cache_dirs()

    cached_pmids = {
        (paper.get("PMID") or "").strip()
        for paper in fulltext_cached
        if (paper.get("PMID") or "").strip()
    }

    pmids: list[str] = []
    pmid_overrides: dict[str, dict[str, str]] = {}
    for paper in papers_without_abstract:
        pmid = (paper.get("PMID") or "").strip()
        if not pmid:
            paper["fulltext_status"] = "no_pmid"
            fulltext_errors.append(
                {
                    "pmid": "",
                    "title": paper.get("Title", ""),
                    "status": "no_pmid",
                    "detail": "missing PMID",
                }
            )
            continue

        if pmid in cached_pmids:
            cached_pdf = PDF_CACHE_DIR / f"PMID_{pmid}.pdf"
            if cached_pdf.exists():
                print(f"[PDF] PMID_{pmid} cache hit: {cached_pdf}")
            continue

        pmids.append(pmid)
        doi = (paper.get("DOI") or paper.get("doi") or "").strip()
        pmcid = (paper.get("PMCID") or paper.get("pmcid") or "").strip()
        if doi or pmcid:
            pmid_overrides[pmid] = {"doi": doi, "pmcid": pmcid}

    pdf_results: dict[str, dict[str, str]] = {}
    md_results: dict[str, dict[str, str]] = {}
    if pmids:
        pdf_need = [pmid for pmid in pmids if not (PDF_CACHE_DIR / f"PMID_{pmid}.pdf").exists()]
        if pdf_need:
            print(f"Starting full-text download (PDF) | 输出目录: {PDF_CACHE_DIR}")
        else:
            print("PDF cache hit, no download needed.")
        pdf_results = download_pdfs_batch(
            pmids,
            pmid_overrides,
            source_strategy=source_strategy,
        )
        md_results = convert_pdfs_to_markdown(pdf_results)

    fulltext_ready: list[dict[str, Any]] = []
    for paper in fulltext_cached:
        if (paper.get("fulltext_markdown") or "").strip():
            paper["fulltext_status"] = "converted"
            paper["screening_stage"] = "full_text"
            fulltext_ready.append(paper)

    for paper in papers_without_abstract:
        pmid = (paper.get("PMID") or "").strip()
        if not pmid or pmid in cached_pmids:
            continue

        pdf_info = pdf_results.get(pmid, {})
        md_info = md_results.get(pmid, {})
        if pdf_info.get("status") != "downloaded":
            _append_fulltext_error(
                paper,
                fulltext_errors,
                pdf_info.get("status", "download_failed"),
                pdf_info.get("error", ""),
            )
            continue

        if md_info.get("status") != "converted":
            _append_fulltext_error(
                paper,
                fulltext_errors,
                md_info.get("status", "conversion_failed"),
                md_info.get("error", ""),
            )
            continue

        md_path = md_info.get("md_path", "")
        paper["fulltext_path"] = md_path
        paper["fulltext_status"] = "converted"
        paper["screening_stage"] = "full_text"
        try:
            paper["fulltext_markdown"] = Path(md_path).read_text(encoding="utf-8")
            fulltext_ready.append(paper)
        except Exception:
            _append_fulltext_error(
                paper,
                fulltext_errors,
                "read_failed",
                "read markdown failed",
            )

    print(f"Full-text screening included: {len(fulltext_ready)}/{total_fulltext}")
    return fulltext_ready, pdf_results, md_results


def _normalize_pmcid(pmcid: str) -> str:
    return re.sub(r"^.*?(PMC\d+).*$", r"\1", pmcid or "", flags=re.IGNORECASE)


def _first_downloaded_pdf(url_results: list[dict[str, Any]]) -> Path | None:
    for info in url_results:
        local_path = info.get("local_path")
        if local_path and Path(local_path).exists():
            return Path(local_path)
    return None


def _append_fulltext_error(
    paper: dict[str, Any],
    fulltext_errors: list[dict[str, str]],
    status: str,
    detail: str,
) -> None:
    paper["fulltext_status"] = status
    fulltext_errors.append(
        {
            "pmid": (paper.get("PMID") or "").strip(),
            "title": paper.get("Title", ""),
            "status": status,
            "detail": detail,
        }
    )
