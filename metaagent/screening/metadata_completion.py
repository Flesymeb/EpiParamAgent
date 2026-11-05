"""Derived, resumable bibliographic completion; no labels, inference or source edits."""

from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = {
    "title": ("title", "Title"),
    "abstract": ("abstract", "Abstract"),
    "keywords": ("keywords", "Keywords"),
    "mesh_terms": ("mesh_terms", "MeSH", "mesh"),
    "pub_types": ("pub_types", "publication_types", "Publication Types"),
    "language": ("language", "Language", "languages"),
    "publication_date": ("publication_date", "Publication Date"),
    "year": ("year", "Publication Year", "publication year"),
    "journal": ("journal", "Journal/Book", "journal/book"),
    "authors": ("authors", "Authors"),
}
IDENTITY = (
    "record_id",
    "pmid",
    "PMID",
    "doi",
    "DOI",
    "pmcid",
    "source_version",
    "preprint_version",
    "version",
    "report_version_id",
    "original_native_version_id",
    "native_id",
    "native_database",
)
VERSIONS = (
    "source_version",
    "preprint_version",
    "version",
    "report_version_id",
    "original_native_version_id",
)


def present(v):
    return v is not None and v != [] and v != {} and bool(str(v).strip())


def get_field(row, field):
    return next((row[k] for k in FIELDS[field] if present(row.get(k))), None)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def doi(v):
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/", "", str(v or "").strip(), flags=re.I
    ).lower()


def version(row):
    return str(next((row[k] for k in VERSIONS if present(row.get(k))), ""))


def identity(row):
    p = str(row.get("pmid") or row.get("PMID") or "").strip()
    d = doi(row.get("doi") or row.get("DOI"))
    return (
        "pmid:" + p
        if p.isdigit()
        else "doi:" + d
        if d
        else "record:" + str(row.get("record_id", ""))
    ) + ("|version:" + version(row) if version(row) else "")


def compatible(row, candidate):
    a = str(row.get("pmid") or row.get("PMID") or "")
    b = str(candidate.get("pmid") or candidate.get("PMID") or "")
    ad, bd = (
        doi(row.get("doi") or row.get("DOI")),
        doi(candidate.get("doi") or candidate.get("DOI")),
    )
    if a and b and a != b or ad and bd and ad != bd:
        return False
    if version(row) and version(row) != version(candidate):
        return False
    return bool(a and a == b or ad and ad == bd or identity(row) == identity(candidate))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def parse_pubmed_xml(data):
    """Reuse the current PubMed parser, distinguishing author keywords from MeSH."""
    from tools.scripts.pubmed_manager import _parse_pubmed_article_details

    root = ET.fromstring(data)
    for article in root.findall(".//PubmedArticle"):
        item = _parse_pubmed_article_details(article)
        if not item.get("pmid"):
            continue
        for field, path in [
            ("keywords", "./MedlineCitation/KeywordList/Keyword"),
            (
                "mesh_terms",
                "./MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName",
            ),
            (
                "pub_types",
                "./MedlineCitation/Article/PublicationTypeList/PublicationType",
            ),
            ("language", "./MedlineCitation/Article/Language"),
        ]:
            item[field] = [
                "".join(n.itertext()).strip()
                for n in article.findall(path)
                if "".join(n.itertext()).strip()
            ]
        date = article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate")
        if date is not None:
            item["publication_date"] = (
                "-".join(
                    date.findtext(k, "").strip()
                    for k in ("Year", "Month", "Day")
                    if date.findtext(k, "").strip()
                )
                or date.findtext("MedlineDate", "").strip()
            )
        # Direct IDs only: never cited references.
        for n in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if n.get("IdType") == "doi" and n.text:
                item["doi"] = n.text.strip()
        yield item


class MetadataLedger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS records(identity TEXT PRIMARY KEY,pmid TEXT,doi TEXT,payload TEXT); CREATE INDEX IF NOT EXISTS idx_pmid ON records(pmid); CREATE INDEX IF NOT EXISTS idx_doi ON records(doi); CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY,sha TEXT); CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS conflicts(key TEXT PRIMARY KEY, identity TEXT, payload TEXT);"
        )

    def add(self, row, source):
        key = identity(row)
        old = self.db.execute(
            "SELECT payload FROM records WHERE identity=?", (key,)
        ).fetchone()
        item = json.loads(old[0]) if old else {k: row[k] for k in IDENTITY if k in row}
        if old and not compatible(row, item):
            conflict = {
                "reason": "explicit_identifier_or_version_conflict",
                "incoming": {k: row[k] for k in IDENTITY if k in row},
                "stored": {k: item[k] for k in IDENTITY if k in item},
                "source": source,
            }
            self.db.execute(
                "INSERT OR IGNORE INTO conflicts VALUES(?,?,?)",
                (
                    sha(json.dumps(conflict, sort_keys=True).encode()),
                    key,
                    json.dumps(conflict),
                ),
            )
            return False
        origins = item.setdefault("_field_sources", {})
        if source.get("route") in {
            "local_pubmed_xml",
            "online_pubmed",
            "online_europe_pmc",
        } and present(get_field(row, "title")):
            item["_official_title"] = {
                "text": get_field(row, "title"),
                "source": source,
            }

        for f in FIELDS:
            val = get_field(row, f)
            if present(val) and not present(item.get(f)):
                item[f] = val
                origins[f] = source
        self.db.execute(
            "INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
            (
                key,
                str(row.get("pmid") or row.get("PMID") or ""),
                doi(row.get("doi") or row.get("DOI")),
                json.dumps(item, ensure_ascii=False),
            ),
        )
        return True

    def candidates(self, row):
        rows = self.db.execute(
            'SELECT payload FROM records WHERE identity=? OR (pmid<>"" AND pmid=?) OR (doi<>"" AND doi=?)',
            (
                identity(row),
                str(row.get("pmid") or row.get("PMID") or ""),
                doi(row.get("doi") or row.get("DOI")),
            ),
        ).fetchall()
        return [v for r in rows if compatible(row, v := json.loads(r[0]))]

    def enrich(self, row, source):
        out = dict(row)
        origins = dict(out.get("metadata_completion_sources") or {})
        for f in FIELDS:
            if get_field(row, f) is not None:
                origins.setdefault(f, {"route": "input_preserved", **source})
        candidates = self.candidates(row)
        for candidate in candidates:
            for f in FIELDS:
                if get_field(out, f) is None and present(candidate.get(f)):
                    out[f] = candidate[f]
                    origins[f] = candidate["_field_sources"][f]
        official = next(
            (c.get("_official_title") for c in candidates if c.get("_official_title")),
            None,
        )
        if official and official["text"] != get_field(out, "title"):
            out["official_title"] = official["text"]
            origins["official_title"] = official["source"]
        conflicts = [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM conflicts WHERE identity=?", (identity(row),)
            ).fetchall()
        ]
        if (
            official
            and official["text"] != get_field(row, "title")
            and get_field(row, "title")
        ):
            conflicts.append(
                {
                    "reason": "nonempty_input_title_preserved",
                    "field": "title",
                    "official_title": official["text"],
                    "source": official["source"],
                }
            )
        out["metadata_completion_conflicts"] = conflicts
        out["metadata_completion_sources"] = origins
        out["metadata_completion_missing_fields"] = [
            f for f in FIELDS if get_field(out, f) is None
        ]
        return out


def input_files(root):
    return sorted(
        p
        for p in Path(root).glob("profiles/*/raw_*.jsonl")
        if p.name in {"raw_search.jsonl", "raw_pool.jsonl"}
    )


def model_record(row, token):
    out = {"record_id": token}
    for k in (
        "pmid",
        "PMID",
        "doi",
        "DOI",
        "pmcid",
        "source_version",
        "preprint_version",
        "version",
        "report_version_id",
    ):
        if k in row and not re.search(r"sr:.*(?:ref|bib)", str(row[k]), re.I):
            out[k] = row[k]
    if present(row.get("official_title")):
        out["official_title"] = row["official_title"]
    for f in FIELDS:
        v = get_field(row, f)
        if v is not None:
            out[f] = v
    return out


def _run_completion(
    root,
    output,
    *,
    online=False,
    batch_size=200,
    interval_s=0.4,
    max_online_requests=500,
    retry_failed=False,
    xml_roots=(),
):
    import httpx

    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError("Output must be outside frozen input release")
    # A resumed workspace is bound to the same source bytes before any mutation.
    previous_path = output / "PREFLIGHT.json"
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text())
        if previous.get("input_root") != str(root):
            raise ValueError("Resume input root differs; choose a new output directory")
        actual = {
            str(p.relative_to(root)): sha(p.read_bytes()) for p in input_files(root)
        }
        if previous.get("input_sha256") != actual:
            raise ValueError(
                "Resume input bytes changed; choose a new output directory"
            )
    output.mkdir(parents=True, exist_ok=True)
    ledger = MetadataLedger(output / "metadata.sqlite3")
    paths = input_files(root)
    if not paths:
        raise ValueError("No raw_search/raw_pool files")
    inputs = {}
    requested = {}
    xml_paths = set()
    totals = Counter()
    for path in paths:
        digest = sha(path.read_bytes())
        inputs[str(path.relative_to(root))] = digest
        origin = {"route": "local_bibliography", "path": str(path), "sha256": digest}
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            totals["rows"] += 1
            for f in FIELDS:
                totals["missing_" + f] += get_field(row, f) is None
            ledger.add(row, origin)
            requested.setdefault(
                identity(row), {k: row[k] for k in IDENTITY if k in row}
            )
            if row.get("metadata_xml_path"):
                xml_paths.add(Path(row["metadata_xml_path"]))
        ledger.db.commit()
    for directory in xml_roots:
        xml_paths.update(Path(directory).rglob("*.xml"))
    loaded = missing = errors = 0
    for path in sorted(xml_paths):
        if not path.is_file():
            missing += 1
            continue
        data = path.read_bytes()
        digest = sha(data)
        if ledger.db.execute(
            "SELECT 1 FROM sources WHERE path=? AND sha=?",
            (str(path.resolve()), digest + ":parser-v2"),
        ).fetchone():
            continue
        try:
            for row in parse_pubmed_xml(data):
                ledger.add(
                    row,
                    {
                        "route": "local_pubmed_xml",
                        "path": str(path.resolve()),
                        "sha256": digest,
                    },
                )
            ledger.db.execute(
                "INSERT OR REPLACE INTO sources VALUES(?,?)",
                (str(path.resolve()), digest + ":parser-v2"),
            )
            loaded += 1
        except (ET.ParseError, ValueError):
            errors += 1
        if loaded % 20 == 0:
            ledger.db.commit()
    ledger.db.commit()
    preflight = {
        "schema_version": "1",
        "input_root": str(root),
        "files": len(paths),
        "rows": totals["rows"],
        "unique_versioned_identities": len(requested),
        "before": dict(totals),
        "local_xml_loaded": loaded,
        "local_xml_missing": missing,
        "local_xml_errors": errors,
        "input_sha256": inputs,
        "implementation_sha256": sha(Path(__file__).read_bytes()),
        "online": online,
        "max_online_requests": max_online_requests,
    }
    atomic_json(output / "PREFLIGHT.json", preflight)
    print(
        json.dumps(
            {
                "phase": "local_index_complete",
                **{
                    k: preflight[k]
                    for k in (
                        "files",
                        "rows",
                        "unique_versioned_identities",
                        "local_xml_loaded",
                        "local_xml_missing",
                    )
                },
            }
        ),
        flush=True,
    )
    pending = []
    doi_rows = []
    for row in requested.values():
        pmid = str(row.get("pmid") or row.get("PMID") or "")
        key = "pubmed:" + pmid if pmid.isdigit() else identity(row)
        prior = ledger.db.execute(
            "SELECT payload FROM attempts WHERE key=?", (key,)
        ).fetchone()
        if prior and (not retry_failed or json.loads(prior[0]).get("status") == "ok"):
            continue
        if any(
            any(
                s.get("route")
                in {"local_pubmed_xml", "online_pubmed", "online_europe_pmc"}
                for s in c.get("_field_sources", {}).values()
            )
            for c in ledger.candidates(row)
        ):
            continue
        if pmid.isdigit():
            pending.append(pmid)
        elif row.get("doi") or row.get("DOI"):
            doi_rows.append(row)
    pending = sorted(set(pending))
    requests = failures = 0

    def request(client, url, params, key):
        nonlocal requests, failures
        time.sleep(interval_s)
        requests += 1
        event = {
            "key": key,
            "url": url,
            "parameters": params,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        response = None
        try:
            response = client.get(url, params=params)
            event["http_status"] = response.status_code
            event["response_sha256"] = sha(response.content)
            path = (
                output
                / "responses"
                / (sha(key.encode()) + (".xml" if "efetch" in url else ".json"))
            )
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(response.content)
            event["response_path"] = str(path)
            response.raise_for_status()
            event["status"] = "ok"
        except Exception as exc:
            event.update(status="failed", error_type=type(exc).__name__)
            failures += 1
            response = None
        with (output / "REQUESTS.jsonl").open("a", encoding="utf-8") as h:
            h.write(json.dumps(event, ensure_ascii=False) + "\n")
        return response, event

    if online:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            for start in range(0, len(pending), batch_size):
                if requests >= max_online_requests:
                    break
                chunk = pending[start : start + batch_size]
                response, event = request(
                    client,
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                    {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"},
                    "pmids:" + ",".join(chunk),
                )
                found = set()
                if response is not None:
                    try:
                        for item in parse_pubmed_xml(response.content):
                            if item["pmid"] in chunk:
                                found.add(item["pmid"])
                                ledger.add(
                                    item,
                                    {
                                        "route": "online_pubmed",
                                        "path": event["response_path"],
                                        "sha256": event["response_sha256"],
                                    },
                                )
                    except ET.ParseError:
                        event["status"] = "invalid_xml"
                for pmid in chunk:
                    ledger.db.execute(
                        "INSERT OR REPLACE INTO attempts VALUES(?,?)",
                        (
                            "pubmed:" + pmid,
                            json.dumps(
                                {
                                    **event,
                                    "status": "ok" if pmid in found else "not_returned",
                                }
                            ),
                        ),
                    )
                ledger.db.commit()
                print(
                    json.dumps(
                        {
                            "phase": "online_pubmed",
                            "requests": requests,
                            "processed": start + len(chunk),
                            "total": len(pending),
                            "returned": len(found),
                        }
                    ),
                    flush=True,
                )
            for row in doi_rows:
                if requests >= max_online_requests:
                    break
                key = identity(row)
                if version(row):
                    ledger.db.execute(
                        "INSERT OR REPLACE INTO attempts VALUES(?,?)",
                        (
                            key,
                            json.dumps({"status": "version_specific_metadata_pending"}),
                        ),
                    )
                    continue
                response, event = request(
                    client,
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    {
                        "query": 'DOI:"' + doi(row.get("doi") or row.get("DOI")) + '"',
                        "format": "json",
                        "resultType": "core",
                        "pageSize": 10,
                    },
                    key,
                )
                found = False
                if response is not None:
                    try:
                        matches = [
                            r
                            for r in response.json()
                            .get("resultList", {})
                            .get("result", [])
                            if doi(r.get("doi"))
                            == doi(row.get("doi") or row.get("DOI"))
                        ]
                        if len(matches) == 1:
                            r = matches[0]
                            item = {
                                "doi": r.get("doi"),
                                "pmid": r.get("pmid", ""),
                                "title": r.get("title"),
                                "abstract": r.get("abstractText"),
                                "keywords": r.get("keywordList", {}).get("keyword", []),
                                "pub_types": r.get("pubTypeList", {}).get(
                                    "pubType", []
                                ),
                                "language": r.get("language"),
                                "publication_date": r.get("firstPublicationDate"),
                                "year": r.get("pubYear"),
                                "authors": r.get("authorString"),
                                "journal": r.get("journalInfo", {})
                                .get("journal", {})
                                .get("title"),
                            }
                            found = ledger.add(
                                item,
                                {
                                    "route": "online_europe_pmc",
                                    "path": event["response_path"],
                                    "sha256": event["response_sha256"],
                                },
                            )
                    except (ValueError, TypeError):
                        pass
                ledger.db.execute(
                    "INSERT OR REPLACE INTO attempts VALUES(?,?)",
                    (
                        key,
                        json.dumps(
                            {
                                **event,
                                "status": "ok"
                                if found
                                else "not_returned_or_ambiguous",
                            }
                        ),
                    ),
                )
                ledger.db.commit()
    coverage = []
    conflict_rows = 0
    before_all = Counter()
    after_all = Counter()
    with (output / "MODEL_IDENTITY_MAP.jsonl").open("w", encoding="utf-8") as mapping:
        for path in paths:
            rel = path.relative_to(root)
            enriched = output / "enriched" / rel
            visible = output / "model_inputs" / rel
            enriched.parent.mkdir(parents=True, exist_ok=True)
            visible.parent.mkdir(parents=True, exist_ok=True)
            before = Counter()
            after = Counter()
            count = 0
            with (
                enriched.with_suffix(".tmp").open("w", encoding="utf-8") as eh,
                visible.with_suffix(".tmp").open("w", encoding="utf-8") as mh,
            ):
                for line in path.open(encoding="utf-8"):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    count += 1
                    out = ledger.enrich(
                        row, {"path": str(path), "sha256": inputs[str(rel)]}
                    )
                    conflict_rows += bool(out.get("metadata_completion_conflicts"))
                    for f in FIELDS:
                        before[f] += get_field(row, f) is not None
                        after[f] += get_field(out, f) is not None
                    eh.write(json.dumps(out, ensure_ascii=False) + "\n")
                    token = "record_" + sha((str(rel) + ":" + str(count)).encode())[:20]
                    mh.write(
                        json.dumps(model_record(out, token), ensure_ascii=False) + "\n"
                    )
                    mapping.write(
                        json.dumps(
                            {
                                "input": str(rel),
                                "row": count,
                                "model_record_id": token,
                                "original_record_id": row.get("record_id"),
                                "original_identity": identity(row),
                            }
                        )
                        + "\n"
                    )
            enriched.with_suffix(".tmp").replace(enriched)
            visible.with_suffix(".tmp").replace(visible)
            before_all.update(before)
            after_all.update(after)
            coverage.append(
                {
                    "input": str(rel),
                    "records": count,
                    "before_present": dict(before),
                    "after_present": dict(after),
                    "added": {f: after[f] - before[f] for f in FIELDS},
                    "after_missing": {f: count - after[f] for f in FIELDS},
                }
            )
    unchanged = all(
        sha((root / rel).read_bytes()) == digest for rel, digest in inputs.items()
    )
    report = {
        **preflight,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "requests_this_invocation": requests,
        "request_failures_this_invocation": failures,
        "pending_pubmed_before_online": len(pending),
        "pending_doi_before_online": len(doi_rows),
        "input_hashes_unchanged": unchanged,
        "field_present_before": dict(before_all),
        "field_present_after": dict(after_all),
        "field_missing_after": {f: totals["rows"] - after_all[f] for f in FIELDS},
        "coverage": coverage,
        "rows_with_metadata_conflicts": conflict_rows,
        "lookup_status_counts": dict(
            Counter(
                json.loads(r[0]).get("status", "unknown")
                for r in ledger.db.execute("SELECT payload FROM attempts")
            )
        ),
        "scientific_labels_used": False,
        "unknowns_inferred": False,
    }
    atomic_json(output / "COVERAGE_REPORT.json", report)
    ledger.db.close()
    print(
        json.dumps(
            {
                "phase": "complete",
                "rows": totals["rows"],
                "requests": requests,
                "input_hashes_unchanged": unchanged,
                "field_missing_after": report["field_missing_after"],
            }
        ),
        flush=True,
    )
    return report


def run_completion(root, output, **kwargs):
    """Hold one writer per derived workspace; safe to retry after interruption."""
    import fcntl

    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError("Output must be outside frozen input release")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".completion.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Metadata completion is already running in this workspace"
            ) from exc
        try:
            return _run_completion(root, output, **kwargs)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
