from __future__ import annotations

"""Extract coding sheet data from PDFs.

This script processes PDFs (local or URLs) to extract structured data using:
  1. PDF → Text extraction (local parser or MinerU)
  2. Text → Structured data (LLM extraction)

Usage Examples:
  # Debug mode - test with first 3 URLs only
  python scripts/run_extraction.py --input papers/scihub_urls.txt --out output/ --method mineru --mode debug

  # Production - process all files
  python scripts/run_extraction.py --input papers/scihub_urls.txt --out output/ --method mineru --mode run

  # Local PDFs with built-in parser
  python scripts/run_extraction.py --input papers/pdfs/ --out output/ --method local

Output Structure:
  output/run_YYYYMMDD_HHMMSS/
    ├── coding_sheet_*.xlsx        # Main extraction results
    ├── coding_sheet_*.csv          # CSV version
    ├── pdf_meta.json               # Metadata
    ├── mineru_assets/              # MinerU raw outputs
    │   └── [DOI_based_name]/       # Per-file assets (markdown, images)
    └── debug/                      # Debug info
"""

import argparse
import sys
import json
import tempfile
import random
import time
import requests
import cloudscraper
from pathlib import Path
from datetime import datetime

try:
    from fake_useragent import UserAgent

    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

# Allow running without installation
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coding_sheet import extract_batch, export_coding_sheet
from coding_sheet.config_schema import load_config, list_templates
from coding_sheet.extraction.pdf_reader import extract_pdf_images, extract_pdf_text
from coding_sheet.utils.doi_resolver import (
    extract_doi_from_text,
    resolve_doi_metadata,
    extract_year_from_pdf_text,
)

# Import MinerU extractor only if needed or handle import error if optional?
# Assuming it's available since it was in the other script.
from coding_sheet.extraction.pdf_reader_mineru import extract_pdf_markdown_mineru

from script_utils import setup_logging, iter_pdfs, safe_slug, read_urls

logger = setup_logging("run_extraction")


def process_local(args, pdfs, out_dir):

    pdf_meta: dict[str, dict] = {}
    papers: list[dict] = []

    for pdf in pdfs:
        extracted = extract_pdf_text(pdf, max_pages=args.max_pages)
        title = extracted.title or pdf.stem

        logger.info(
            "PDF %s: pages=%d max_pages=%s extracted_chars=%d",
            pdf.name,
            extracted.page_count,
            str(args.max_pages),
            extracted.extracted_char_count,
        )

        if extracted.likely_scanned:
            logger.warning(
                "PDF looks scanned / low text extracted: %s (chars=%d). Consider OCR later.",
                pdf.name,
                extracted.extracted_char_count,
            )

        full_text = extracted.text

        # Note: Don't truncate here if using config with extraction settings
        # Only apply command-line truncation if no config is specified
        if args.max_fulltext_chars and len(full_text) > args.max_fulltext_chars:
            if not (args.config or args.template):
                full_text = (
                    full_text[: args.max_fulltext_chars] + "\n\n[... truncated ...]"
                )

        if args.extract_images:
            img_dir = out_dir / "pdf_images"
            imgs = extract_pdf_images(pdf, out_dir=img_dir, max_pages=args.max_pages)
            logger.info("Extracted %d images from %s", len(imgs), pdf.name)

        # Try to extract DOI and resolve metadata
        doi = extract_doi_from_text(full_text)
        year_from_doi = None
        if doi:
            logger.info(f"Found DOI in {pdf.name}: {doi}")
            doi_meta = resolve_doi_metadata(doi)
            if doi_meta and doi_meta.get("year"):
                year_from_doi = doi_meta["year"]
                logger.info(f"Resolved year from DOI: {year_from_doi}")

        # Fallback: try to extract year from PDF text
        if not year_from_doi:
            year_from_doi = extract_year_from_pdf_text(full_text)
            if year_from_doi:
                logger.info(f"Extracted year from PDF text: {year_from_doi}")

        papers.append(
            {
                "id": f"PDF:{pdf.stem}",
                "title": title,
                "abstract": "",
                "full_text": full_text,
                "doi": doi,
                "year": year_from_doi,
                "source": "pdf",
            }
        )
        pdf_meta[f"PDF:{pdf.stem}"] = {
            "filename": pdf.name,
            "page_count": extracted.page_count,
            "extracted_chars": extracted.extracted_char_count,
            "doi": doi,
            "year": year_from_doi,
        }

    return papers, pdf_meta


def process_mineru(args, items, out_dir):
    pdf_meta: dict[str, dict] = {}
    papers: list[dict] = []

    debug_dir = out_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        is_url = isinstance(item, str) and str(item).lower().startswith(
            ("http://", "https://")
        )

        # Allow URL lists to contain already-downloaded local file paths (strings).
        if isinstance(item, str) and not is_url:
            p = Path(item)
            if p.exists() and p.is_file():
                item = p

        if is_url:
            pdf_url = item
            original_source_url = pdf_url
            # Create a safe slug from the URL for filename/ID
            # Try to extract DOI if present in URL (e.g., /pdf/10.1177/123.pdf)
            url_parts = item.split("/")
            potential_doi = "/".join(
                [p for p in url_parts if "." in p and not p.endswith(".pdf")]
            ).replace(".pdf", "")
            if potential_doi and "/" in potential_doi:
                stem = safe_slug(potential_doi)  # Use DOI as identifier
            else:
                stem = safe_slug(url_parts[-1].replace(".pdf", ""))
            name = f"{stem}.pdf"
            pdf_path = Path(name)  # Dummy path
            logger.info("Processing URL via MinerU: %s [ID: %s]", item, stem)
        else:
            # Local file
            pdf_path = item
            stem = item.stem
            name = item.name
            pdf_url = None
            original_source_url = None
            if args.pdf_url_template:
                pdf_url = args.pdf_url_template.format(stem=stem, name=name)
            logger.info("Processing PDF via MinerU: %s", name)

        # Prepare params for MinerU config
        mineru_params = {}
        if args.mineru_base_url:
            mineru_params["mineru_base_url"] = args.mineru_base_url
        if args.mineru_endpoint:
            mineru_params["mineru_endpoint"] = args.mineru_endpoint
        if args.mineru_timeout_s:
            mineru_params["mineru_timeout_s"] = args.mineru_timeout_s

        # Output dir for this PDF's assets
        pdf_out_dir = out_dir / "mineru_assets" / stem
        pdf_out_dir.mkdir(parents=True, exist_ok=True)

        # If it's a URL (especially Sci-Hub), download to temp file first
        temp_pdf_path = None
        if is_url:
            logger.info("Downloading PDF from: %s", pdf_url)
            try:
                # Create cloudscraper session to bypass DDoS-Guard
                scraper = cloudscraper.create_scraper(
                    browser={
                        "browser": "chrome",
                        "platform": "windows",
                        "mobile": False,
                    }
                )

                # Generate realistic browser headers with random user agent
                if HAS_FAKE_UA:
                    ua = UserAgent()
                    user_agent = ua.random
                else:
                    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

                # Extract domain for referer
                from urllib.parse import urlparse

                parsed = urlparse(pdf_url)
                referer = f"{parsed.scheme}://{parsed.netloc}/"

                headers = {
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Referer": referer,
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-User": "?1",
                }

                # Random delay before download to avoid detection
                time.sleep(random.uniform(0.5, 1.5))

                # Use cloudscraper to bypass DDoS-Guard
                response = scraper.get(pdf_url, headers=headers, timeout=30)
                response.raise_for_status()
                pdf_data = response.content

                # Verify it's actually a PDF
                if pdf_data[:4] != b"%PDF":
                    raise ValueError(
                        f"Downloaded content is not a PDF (starts with: {pdf_data[:20]})"
                    )

                # Save to temp file
                temp_pdf = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".pdf", prefix=f"{stem}_"
                )
                temp_pdf.write(pdf_data)
                temp_pdf.close()
                temp_pdf_path = Path(temp_pdf.name)
                logger.info(
                    "Downloaded %d bytes to: %s", len(pdf_data), temp_pdf_path.name
                )

                # Use local file path instead of URL
                pdf_path = temp_pdf_path
                pdf_url = None  # Don't use URL mode
            except Exception as e:
                logger.error("Failed to download PDF from %s: %s", item, e)
                if args.continue_on_error:
                    err_info = {"file": str(item), "error": f"Download failed: {e}"}
                    (debug_dir / f"{stem}_error.json").write_text(
                        json.dumps(err_info, indent=2), encoding="utf-8"
                    )
                    continue
                else:
                    raise

        try:
            logger.info("Extracting via MinerU (model=%s)...", args.model_version)
            extracted = extract_pdf_markdown_mineru(
                pdf_path=pdf_path,
                pdf_url=pdf_url,
                model_version=args.model_version,
                params=mineru_params,
                output_dir=pdf_out_dir,
            )
            logger.info(
                "MinerU extraction success: %d chars extracted",
                extracted.extracted_char_count,
            )
        except Exception as e:
            logger.error("MinerU extraction failed for %s: %s", name, e)
            # Clean up temp file if exists
            if temp_pdf_path and temp_pdf_path.exists():
                temp_pdf_path.unlink()
                logger.debug("Cleaned up temp file: %s", temp_pdf_path)

            if args.continue_on_error:
                # Write debug info
                err_info = {"file": str(item), "error": str(e)}
                (debug_dir / f"{stem}_error.json").write_text(
                    json.dumps(err_info, indent=2), encoding="utf-8"
                )
                continue
            else:
                raise
        finally:
            # Always clean up temp file
            if temp_pdf_path and temp_pdf_path.exists():
                temp_pdf_path.unlink()
                logger.debug("Cleaned up temp file: %s", temp_pdf_path)

        # Save raw result for debug
        (debug_dir / f"{stem}_mineru.json").write_text(
            json.dumps(extracted.raw_response, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        full_text = extracted.markdown

        # Note: Don't truncate here if using config with extraction settings
        # The extract_batch function will handle truncation based on config
        # Only apply command-line truncation if explicitly set
        if args.max_fulltext_chars and len(full_text) > args.max_fulltext_chars:
            # Check if we have a config that might override this
            if not (args.config or args.template):
                # No config, apply command-line truncation
                full_text = (
                    full_text[: args.max_fulltext_chars] + "\n\n[... truncated ...]"
                )
            # else: Let config handle truncation in extract_batch

        # Try to extract title from markdown (usually first heading)
        extracted_title = None
        for line in full_text.split("\n")[:20]:  # Check first 20 lines
            line = line.strip()
            if line.startswith("#"):
                extracted_title = line.lstrip("#").strip()
                break

        if extracted_title:
            logger.info("Extracted title: %s", extracted_title[:100])
        else:
            logger.warning("Could not extract title from markdown")

        # Try to extract DOI and resolve metadata
        doi = extract_doi_from_text(full_text)
        year_from_doi = None
        if doi:
            logger.info(f"Found DOI in {stem}: {doi}")
            doi_meta = resolve_doi_metadata(doi)
            if doi_meta and doi_meta.get("year"):
                year_from_doi = doi_meta["year"]
                logger.info(f"Resolved year from DOI: {year_from_doi}")

        # Fallback: try to extract year from PDF text
        if not year_from_doi:
            year_from_doi = extract_year_from_pdf_text(full_text)
            if year_from_doi:
                logger.info(f"Extracted year from PDF text: {year_from_doi}")

        papers.append(
            {
                "id": f"PDF:{stem}",
                "title": extracted_title or stem,  # Use extracted title if available
                "abstract": "",
                "full_text": full_text,
                "doi": doi,
                "year": year_from_doi,
                "source": "mineru_pdf",
            }
        )
        pdf_meta[f"PDF:{stem}"] = {
            "filename": name,
            "extracted_chars": len(full_text),
            "mineru_model": args.model_version,
            "extracted_title": extracted_title,
            "source_url": original_source_url,
            "doi": doi,
            "year": year_from_doi,
        }

    return papers, pdf_meta


def main():
    ap = argparse.ArgumentParser(
        description="Extract text from PDFs using local parser or MinerU."
    )
    ap.add_argument(
        "--input", required=True, help="PDF file or directory containing PDFs"
    )
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument(
        "--mode",
        choices=["run", "debug"],
        default="run",
        help="Execution mode: 'run' processes all files, 'debug' limits to 3 for testing",
    )
    ap.add_argument(
        "--method",
        choices=["local", "mineru"],
        default="local",
        help="Extraction method",
    )
    ap.add_argument("--max-fulltext-chars", type=int, default=20000)

    # Schema configuration
    ap.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file for custom schema",
    )
    ap.add_argument(
        "--template",
        type=str,
        default=None,
        choices=list_templates() + [None],
        help=f"Built-in template to use: {list_templates()}",
    )

    # Local specific
    ap.add_argument(
        "--max-pages", type=int, default=30, help="[Local] Max pages to parse"
    )
    ap.add_argument(
        "--extract-images",
        action="store_true",
        help="[Local] Also export embedded images",
    )

    # MinerU specific
    ap.add_argument("--model-version", default="vlm", help="[MinerU] Model version")
    ap.add_argument(
        "--mineru-base-url", default=None, help="[MinerU] Override MINERU_BASE_URL"
    )
    ap.add_argument(
        "--mineru-endpoint", default=None, help="[MinerU] Override MINERU_ENDPOINT"
    )
    ap.add_argument(
        "--mineru-timeout-s",
        type=int,
        default=None,
        help="[MinerU] Override MINERU_TIMEOUT_S",
    )
    ap.add_argument(
        "--pdf-url-template",
        default=None,
        help="[MinerU] URL template for remote access",
    )
    ap.add_argument(
        "--continue-on-error", action="store_true", help="[MinerU] Continue on error"
    )

    args = ap.parse_args()

    input_path = Path(args.input)
    base_out_dir = Path(args.out)

    # Create timestamped subdirectory for this run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "debug" if args.mode == "debug" else "run"
    out_dir = base_out_dir / f"{prefix}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", out_dir)

    # Check if input is a URL list
    urls = []
    if input_path.is_file() and input_path.suffix.lower() in (".txt", ".jsonl"):
        urls = read_urls(input_path)
        if urls:
            logger.info(f"Loaded {len(urls)} URLs from {input_path}")
            if args.mode == "debug" and len(urls) > 3:
                logger.warning(
                    "DEBUG MODE: Limiting to first 3 URLs (out of %d)", len(urls)
                )
                urls = urls[:3]
            logger.info(
                "Input treated as URL list (%d items). Local PDF paths in the list are supported.",
                len(urls),
            )

    pdfs = []
    if not urls:
        pdfs = iter_pdfs(input_path)
        if not pdfs:
            logger.error(f"No PDFs or URLs found under: {input_path}")
            sys.exit(1)
        logger.info(f"Found {len(pdfs)} PDFs. Method: {args.method}")
        if args.mode == "debug" and len(pdfs) > 3:
            logger.warning(
                "DEBUG MODE: Limiting to first 3 PDFs (out of %d)", len(pdfs)
            )
            pdfs = pdfs[:3]

    if args.method == "local":
        if urls:
            logger.error(
                "Local extraction does not support URL lists. Please download them first."
            )
            sys.exit(1)
        papers, pdf_meta = process_local(args, pdfs, out_dir)
    else:
        # MinerU supports both
        items = urls if urls else pdfs
        papers, pdf_meta = process_mineru(args, items, out_dir)

    if not papers:
        logger.warning("No papers extracted.")
        return

    # Run extraction batch (LLM processing)
    logger.info("Running LLM extraction on %d papers...", len(papers))

    # Determine schema configuration
    schema_config = None
    if args.config:
        logger.info("Using custom config: %s", args.config)
        schema_config = load_config(args.config)
    elif args.template:
        logger.info("Using template: %s", args.template)
        schema_config = load_config(args.template)
    else:
        logger.info("Using legacy schema (no config specified)")

    batch = extract_batch(
        papers,
        max_fulltext_chars=args.max_fulltext_chars,
        config=schema_config,
    )

    logger.info(
        "Done. papers=%d success=%d failed=%d records=%d needs_review=%d",
        batch.total_papers,
        batch.successful_papers,
        batch.failed_papers,
        batch.total_records,
        batch.needs_review,
    )

    # Export - gather all records from all results
    all_records = []
    for result in batch.results:
        record_count = len(result.records)
        logger.info(
            "  Paper '%s': status=%s, records=%d",
            result.paper_title[:80] if result.paper_title else result.paper_id,
            result.status,
            record_count,
        )
        if result.status == "failed":
            logger.error("    Errors: %s", result.errors)

        # Save raw LLM output to debug directory
        if result.raw_llm_output:
            safe_id = "".join(c if c.isalnum() else "_" for c in result.paper_id[:50])
            llm_output_file = out_dir / "debug" / f"{safe_id}_llm_output.txt"
            llm_output_file.write_text(result.raw_llm_output, encoding="utf-8")

        all_records.extend(result.records)

    if all_records:
        export_coding_sheet(all_records, out_dir=out_dir, config=schema_config)
        logger.info("Exported %d records to coding sheet.", len(all_records))
    else:
        logger.warning("No records to export.")

    # Save metadata
    (out_dir / "pdf_meta.json").write_text(
        json.dumps(pdf_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("=" * 60)
    logger.info("All results saved to: %s", out_dir)
    logger.info("  - Coding sheets: coding_sheet_*.xlsx/csv")
    logger.info("  - MinerU assets: mineru_assets/")
    logger.info("  - Debug info: debug/")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
