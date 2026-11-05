"""Source-specific retrieval with explicit coverage and failure artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.literature.cli import merge
from tools.literature.sources import now, search


def search_sources(queries: dict[str, str], directory: Path, *, limit: int | None,
                   complete_pubmed, page_cache: Path | None = None) -> tuple[list[dict], dict]:
    """Retain PubMed exhaustive retrieval; other adapters expose bounded coverage.

    Source failure does not discard successful sources. Callers must carry the
    resulting failed-source count into the run's partial status.
    """
    records, outcomes = [], []
    directory.mkdir(parents=True, exist_ok=True)
    for source, query in queries.items():
        target = directory / source
        target.mkdir(exist_ok=True)
        try:
            if source == "pubmed" and limit is None:
                rows, details = complete_pubmed(query, target)
                total = details.get("total_matches")
                actual = query
                complete = bool(details.get("retrieval_complete"))
                adapter = "partitioned_pubmed"
            elif limit is None:
                audit = {}
                def checkpoint(page, state, cursor):
                    token = f"page_{state['pages']:06d}"
                    (target / (token + '.json')).write_text(json.dumps(page, ensure_ascii=False))
                    (target / 'checkpoint.json').write_text(json.dumps({**state, 'cursor': cursor, 'query_sha256': hashlib.sha256(query.encode()).hexdigest()}, ensure_ascii=False))
                rows, total, actual = search(source, query, None, audit=audit, checkpoint=checkpoint, **({"page_cache": page_cache / source} if page_cache is not None else {}))
                complete = audit['complete']
                adapter = 'europepmc_preprint' if source in {'medrxiv', 'biorxiv'} else source
            else:
                rows, total, actual = search(source, query, limit)
                complete = False  # Provider counts alone do not certify coverage.
                adapter = "europepmc_preprint" if source in {"medrxiv", "biorxiv"} else source
            export = target / "records.jsonl"
            export.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))
            for row in rows:
                row["source"] = source
                row.setdefault("source_id", row.get("record_id") or row.get("pmid") or row.get("doi", ""))
            records.extend(rows)
            outcomes.append(dict(source=source, adapter=adapter, query=actual, total_matches=total,
                                 retrieved=len(rows), retrieval_complete=complete, status="success",
                                 export=str(export), limit=limit))
        except Exception as exc:
            # Exception bodies may contain signed URLs or credentials.
            outcomes.append(dict(source=source, query=query, status="failed", error_type=type(exc).__name__, retrieval_complete=False))
    stats = dict(executed_at=now(), sources=outcomes, retrieved_before_merge=len(records),
                 retrieval_complete=all(r["retrieval_complete"] for r in outcomes),
                 failed_sources=sum(r["status"] == "failed" for r in outcomes),
                 incomplete_sources=sum(r["status"] == "success" and not r["retrieval_complete"] for r in outcomes) if limit is None else 0)
    merged = merge(records)
    stats["retrieved"] = len(merged)
    (directory / "retrieval_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    return merged, stats
