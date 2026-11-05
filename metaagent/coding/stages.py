"""Coding stages with explicit bypasses and source-bound candidate artifacts.

The backend is internal to A. B always receives original source access and never
uses a cached A output when A is disabled. This module has no benchmark dependency.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from decimal import Decimal
from pathlib import Path

from metaagent.coding.schema.config_loader import create_model_from_config
from metaagent.coding.prompt_context import parameter_context, coding_task_context, CODING_PROMPT_VERSION
from metaagent.coding.schema.prompt_factory import generate_field_descriptions
from metaagent.coding.evidence import evidence_locations
from metaagent.coding.validators import numeric_review_flags
from metaagent.coding.completeness import audit_completeness, attributable_pending_signal, coverage_policy, AUDIT_VERSION
from metaagent.evidence_search import search_evidence

ABLATIONS = ("full", "without_a", "without_b")
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "coding"
_DOMAIN_GUIDE = (_PROMPT_DIR / "domain_guide.md").read_text(encoding="utf-8")
DOMAIN_GUIDE_SHA256 = hashlib.sha256(_DOMAIN_GUIDE.encode("utf-8")).hexdigest()
SEMANTICS = (_PROMPT_DIR / "common.md").read_text(encoding="utf-8") + "\n\n" + _DOMAIN_GUIDE
A_SEMANTICS = (_PROMPT_DIR / "stage_a.md").read_text(encoding="utf-8")
A_RULES = A_SEMANTICS + (_PROMPT_DIR / "serialization_json.md").read_text(encoding="utf-8")
B_RULES = (_PROMPT_DIR / "stage_b.md").read_text(encoding="utf-8")
B_SERIALIZATION = (_PROMPT_DIR / "stage_b_serialization.md").read_text(encoding="utf-8")
A_EMPTY_RULES = (_PROMPT_DIR / "stage_a_empty_verification.md").read_text(encoding="utf-8")
B_EVIDENCE_RULES = (_PROMPT_DIR / "stage_b_evidence.md").read_text(encoding="utf-8")
IDENTITY_FIELDS = ("cohort_id", "stratum", "time_window", "method", "statistic", "analysis_role")


def source_blocks(text: str, max_chars: int = 24000, *, overlap: int | None = None,
                  source_id="main", base_offset=0) -> list[dict]:
    """Bounded overlapping source windows with exact, reversible offsets.

    Markdown table headers and footnotes are separately supplied as source segments;
    they do not displace cells or create fabricated offsets in the source text.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*",source_id):
        raise ValueError("source_id must be a safe stable identifier")
    if max_chars < 256:
        raise ValueError("Coding block size must be at least 256 characters")
    if not text.strip():
        raise ValueError("Empty coding source")
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    overlap = min(1000, max_chars//5) if overlap is None else overlap
    if not 0 <= overlap < max_chars:
        raise ValueError("Overlap must be nonnegative and smaller than the block")
    contexts=[]
    lines=list(re.finditer(r"[^\n]*(?:\n|$)",text))
    for i,line in enumerate(lines):
        if re.match(r"^\s*\|?\s*:?-{3,}",line.group()) and i:
            last=i+1
            while last<len(lines) and "|" in lines[last].group() and lines[last].group().strip():
                last+=1
            table_end=lines[last-1].end()
            # Only the headers/footnotes of this table are attached to its rows.
            # Prior tables elsewhere in the document are not contextual evidence.
            notes=[]
            next_line=last
            while next_line<len(lines) and re.match(r"^\s*(?:\[\^.+?\]:|(?:Notes?|Footnotes?):)",lines[next_line].group(),re.I):
                note=lines[next_line];notes.append((note.start(),note.end()))
                table_end=note.end();next_line+=1
            scope_start=lines[i-1].start()
            contexts.append((scope_start,line.end(),"table_header",scope_start,table_end))
            contexts.extend((ns,ne,"footnote",scope_start,table_end) for ns,ne in notes)
    result=[];start=0
    while start<len(text):
        end=min(start+max_chars,len(text))
        if end<len(text):
            boundary=text.rfind("\n",start+max_chars//2,end)
            if boundary>start:end=boundary+1
        segments=[{"source_id":source_id,"start":base_offset+start,"source_start":start,
                   "end":base_offset+end,"text":text[start:end],"role":"body", "source_sha256":source_sha256}]
        # Contexts are exact source slices; the model sees IDs, and the verifier
        # maps quotes back to the original source rather than the rendered prompt.
        budget=max_chars
        for cs,ce,role,scope_start,scope_end in contexts:
            if cs>=start and ce<=end:continue
            if start>=scope_end or end<=scope_start:continue
            if ce-cs<=budget:
                segments.append({"source_id":source_id,"start":base_offset+cs,"source_start":cs,
                                 "end":base_offset+ce,"text":text[cs:ce],"role":role,"source_sha256":source_sha256})
                budget-=ce-cs
        result.append({"block_id":f"{source_id}-block-{len(result)+1}","source_id":source_id,
                       "start":base_offset+start,"end":base_offset+end,"text":text[start:end],
                       "segments":segments})
        if end==len(text):break
        start=max(start+1,end-overlap)
    return result


def _evidence_identity(row, fields):
    anchors={name:sorted((e.get("source_id","main"),e["start"],e["end"]) for e in entries)
             for name,entries in row["field_evidence"].items()}
    return {"fields":{name:row.get(name) for name in fields},"anchors":anchors}


def _stage_source(block):
    return [{k:v for k,v in segment.items() if k!="end"} for segment in block.get("segments",[
        {"source_id":block.get("source_id","main"),"start":block["start"],"source_start":block["start"],"text":block["text"]}])]


def _json(content: str):
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value)
    # Never interpret malformed/truncated JSON as a legitimate empty extraction.
    return json.loads(value)


def _candidate_records(payload):
    """Unwrap the declared LLM envelope, retaining legacy bare-array support.

    Unknown objects and malformed rows are errors, never successful no-record
    results. This changes serialization only; source fields/IDs are not inferred.
    """
    if isinstance(payload, dict) and set(payload) == {"records"}:
        payload = payload["records"]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError('Stage A must return {"records": [...]} or a legacy record array')
    return payload


def _validated(row, config, block, pmid):
    if not isinstance(row, dict):
        raise ValueError("Coding records must be objects")
    data = dict(row)
    fields = {f.name: f for f in config.fields}
    values = {name: data.get(name) for name in fields}
    if "pmid" in fields:
        values["pmid"] = pmid or "NR"
    for name, field in fields.items():
        if values[name] is None and field.required and field.type == "str":
            values[name] = "NR"
    validated = create_model_from_config(config).model_validate(values).model_dump()
    data.update({name: validated[name] for name in fields})
    for value in data.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Coding returned a non-finite number")
    evidence = data.get("_field_evidence") or data.get("field_evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError("Field evidence must be an object")
    issues = []
    proposed_status=data.get("field_status") or {}
    applicability=data.get("applicability_evidence") or {}
    located = {}
    statuses = {}
    for name in dict.fromkeys([*fields, *IDENTITY_FIELDS]):
        value = data.get(name)
        if name == "pmid":
            statuses[name] = "input_identity"
            continue
        if name == "evidence_locations":
            statuses[name] = "derived_provenance"
            continue
        if value is None or value == "NR" or value == []:
            claimed=proposed_status.get(name)
            support=applicability.get(name, "")
            if isinstance(support,dict):support=support.get("quote","")
            if claimed=="not_applicable" and support and any(support in seg["text"] for seg in _stage_source(block)):
                statuses[name]="not_applicable"
            else:
                statuses[name]="unresolved" if claimed in {"reported","unresolved","verified_not_reported","not_applicable"} else "not_found_in_supplied_material"
                if claimed in {"reported","verified_not_reported","not_applicable"}:
                    issues.append("unsupported_field_status:"+name)
            continue
        entries = evidence.get(name, [])
        entries = entries if isinstance(entries, list) else [entries]
        quotes = []
        for entry in entries:
            quote = entry if isinstance(entry, str) else entry.get("quote", entry.get("text", "")) if isinstance(entry, dict) else ""
            matches=[]
            for segment in _stage_source(block):
                if not quote:continue
                for hit in re.finditer(re.escape(quote),segment["text"]):
                    matches.append((segment,hit.start()))
            unique={ (seg.get("source_id","main"),seg["start"]+offset):(seg,offset) for seg,offset in matches}
            for segment,local in unique.values():
                ambiguous=len(unique)>1
                if ambiguous:issues.append("ambiguous_evidence_location:"+name)
                quotes.append({"quote":quote,"start":segment["start"]+local,
                               "end":segment["start"]+local+len(quote),
                               "source_start":segment.get("source_start",segment["start"])+local,
                               "source_end":segment.get("source_start",segment["start"])+local+len(quote),
                               "source_id":segment.get("source_id","main"),
                               "source_sha256":segment.get("source_sha256"),
                               "block_id":block["block_id"],"ambiguous":ambiguous})
        if not quotes:
            issues.append("missing_or_unlocated_evidence:"+name)
            if name in IDENTITY_FIELDS:
                data.setdefault("unverified_identity", {})[name] = data.get(name)
                data[name] = None
        if quotes and isinstance(value,(float,int)) and not isinstance(value,bool):
            tokens=[token.replace(",","") for q in quotes for token in re.findall(r"(?<![\w.])[+-]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?",q["quote"].replace("−","-"))]
            supported=any(Decimal(token)==Decimal(str(value)) for token in tokens)
            if value==0 and name in {"deaths","positive_count"}:
                supported=supported or any(re.search(r"\b(?:no deaths|no positives|zero|none)\b",q["quote"],re.I) for q in quotes)
            if not supported:issues.append("numeric_value_not_in_evidence:"+name)
        statuses[name] = "reported" if quotes else "unresolved"
        located[name] = quotes
    for name in IDENTITY_FIELDS:
        data.setdefault(name, None)
    data["field_status"] = statuses
    data["field_evidence"] = located
    if "evidence_locations" in fields:
        data["evidence_locations"] = evidence_locations(located)
    data.pop("_field_evidence", None)
    data["source_block_id"] = block["block_id"]
    issues.extend(numeric_review_flags(data, config))
    data["review_flags"] = sorted(set(data.get("review_flags", []) + issues))
    data["needs_review"] = bool(data.get("needs_review") or issues)
    return data


def _b_contract_feedback(payload, candidates, error):
    """Describe association failures without inferring an association or answer."""
    expected={r["candidate_id"] for r in candidates}
    rows=payload.get("records",[]) if isinstance(payload,dict) else []
    ds=payload.get("dispositions",[]) if isinstance(payload,dict) else []
    rows=rows if isinstance(rows,list) else []
    ds=ds if isinstance(ds,list) else []
    returned=[r.get("candidate_id") for r in rows if isinstance(r,dict) and isinstance(r.get("candidate_id"),str)]
    actions={}
    for d in ds:
        if isinstance(d,dict) and isinstance(d.get("candidate_id"),str) and d["candidate_id"] in expected and d.get("action") in {"keep","correct","reject","pending"}:
            actions.setdefault(d["candidate_id"],[]).append(d["action"])
    locked={cid:values[0] for cid,values in actions.items() if len(set(values))==1}
    required={cid for cid in expected if locked.get(cid)!="reject"}
    return {"validation_error":str(error),"expected_candidate_ids":sorted(expected),
            "missing_top_level_fields":[key for key in ("records","dispositions") if not isinstance(payload,dict) or key not in payload],
            "missing_disposition_candidate_ids":sorted(expected-{d.get("candidate_id") for d in ds if isinstance(d,dict) and isinstance(d.get("candidate_id"),str)}),
            "required_response_envelope":{"records":"source-grounded records with candidate_id", "dispositions":"one candidate_id/action/reason per supplied candidate"},
            "missing_candidate_ids":sorted(required-set(returned)),
            "unexpected_candidate_ids":sorted(set(returned)-expected),
            "records_missing_candidate_id":[i for i,r in enumerate(rows) if isinstance(r,dict) and "candidate_id" not in r],
            "invalid_disposition_indices":[i for i,d in enumerate(ds) if not isinstance(d,dict) or not isinstance(d.get("candidate_id"),str) or d.get("candidate_id") not in expected],
            "disposition_scope":"Only supplied candidate IDs have dispositions. New source-supported records with candidate_id:null have no disposition entry.",
            "locked_disposition_actions":locked}


def _validate_b_contract(payload, scoped, config, block, pmid, ablation, *, locked_actions=None):
    """Validate a whole block before publishing any record or disposition."""
    if not isinstance(payload,dict) or not isinstance(payload.get("records"),list) or not isinstance(payload.get("dispositions"),list):
        raise ValueError("Stage B must return records and dispositions arrays")
    ids={r["candidate_id"] for r in scoped};ds=payload["dispositions"]
    if any(not isinstance(d,dict) or not isinstance(d.get("candidate_id"),str) for d in ds):
        raise ValueError("Invalid candidate disposition")
    if len(ds)!=len(ids) or {d["candidate_id"] for d in ds}!=ids:
        raise ValueError("Stage B must account for every candidate exactly once")
    actions={d["candidate_id"]:d.get("action") for d in ds}
    if any(a not in {"keep","correct","reject","pending"} for a in actions.values()):
        raise ValueError("Invalid disposition action")
    if any(actions.get(cid)!=action for cid,action in (locked_actions or {}).items()):
        raise ValueError("Contract correction cannot change an existing disposition action")
    seen=set();validated=[]
    for value in payload["records"]:
        if not isinstance(value,dict) or "candidate_id" not in value:
            raise ValueError("Every Stage B record requires explicit candidate_id (null only for additions)")
        cid=value["candidate_id"]
        if cid is not None:
            if not isinstance(cid,str) or cid not in ids or cid in seen or actions[cid]=="reject":
                raise ValueError("Stage B returned an invalid/duplicate/rejected candidate")
            seen.add(cid)
        row=_validated(value,config,block,pmid)
        if cid is None and not any(row["field_evidence"].values()):
            raise ValueError("Stage B additions require located original source evidence")
        row.update(producer="stage_b",ablation=ablation,
                   semantic_review="pending" if row["needs_review"] or actions.get(cid)=="pending" else "reviewed")
        if actions.get(cid)=="pending":row["needs_review"]=True
        validated.append(row)
    if seen!={cid for cid,action in actions.items() if action!="reject"}:
        raise ValueError("Stage B dropped an unrejected candidate")
    return validated,ds


def _unlocated_evidence_targets(payload, validated):
    targets=[]
    for index,(raw,checked) in enumerate(zip(payload["records"],validated)):
        key="_field_evidence" if raw.get("_field_evidence") else "field_evidence"
        evidence=raw.get(key) or {}
        for flag in checked.get("review_flags",[]):
            prefix="missing_or_unlocated_evidence:"
            if not flag.startswith(prefix):continue
            field=flag[len(prefix):]
            if checked.get("field_evidence",{}).get(field):continue
            value=raw.get(field)
            if value is None or value==[] or isinstance(value,str) and value.strip().upper() in {"","NR","N/A","NA","NULL"}:continue
            entries=evidence.get(field,[]);entries=entries if isinstance(entries,list) else [entries]
            quotes=[entry if isinstance(entry,str) else entry.get("quote",entry.get("text","")) if isinstance(entry,dict) else "" for entry in entries]
            quotes=[quote for quote in quotes if isinstance(quote,str) and quote.strip()]
            if quotes:targets.append({"record_index":index,"candidate_id":raw["candidate_id"],"field":field,"original_quotes":quotes,"evidence_key":key})
    return targets


def _apply_evidence_patches(payload, response, targets):
    """Validate the whole patch batch before changing a copy of raw B output."""
    if not isinstance(response,dict) or set(response)!={"evidence_patches"} or not isinstance(response["evidence_patches"],list):
        raise ValueError("Evidence correction requires only an evidence_patches array")
    expected={(t["record_index"],t["field"]):t for t in targets};seen=set();validated=[]
    for patch in response["evidence_patches"]:
        if not isinstance(patch,dict) or set(patch)!={"record_index","candidate_id","field","quotes"}:
            raise ValueError("Evidence patch has missing or extra fields")
        if type(patch["record_index"]) is not int or not isinstance(patch["field"],str):
            raise ValueError("Evidence patch target has invalid types")
        key=(patch["record_index"],patch["field"])
        if key not in expected or key in seen or patch["candidate_id"]!=expected[key]["candidate_id"]:
            raise ValueError("Evidence patch has duplicate, unknown or changed target identity")
        quotes=patch["quotes"]
        if not isinstance(quotes,list) or not quotes or any(not isinstance(q,str) or not q.strip() for q in quotes):
            raise ValueError("Evidence patch quotes must be nonempty strings")
        seen.add(key);validated.append((expected[key],quotes))
    if seen!=set(expected):raise ValueError("Evidence patch must cover every declared target exactly once")
    result=copy.deepcopy(payload)
    for target,quotes in validated:
        result["records"][target["record_index"]][target["evidence_key"]][target["field"]]=quotes
    return result


def _data_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def run_stages(*, text: str, config, record_id: str, pmid: str | None,
               invoke, output_dir: Path, ablation="full", chunk_chars=24000,
               extract_a=None, document_sources=None, stage_a_empty_retries=None) -> list[dict]:
    """Run A/B; invoke(stage_name, messages) returns JSON text.

    extract_a(block, candidate_config) optionally implements LangExtract inside A.
    """
    if ablation not in ABLATIONS:
        raise ValueError(f"Unknown coding ablation: {ablation}")
    coverage_policy(config)  # reject malformed local policy before any model call
    empty_retries=stage_a_empty_retries if stage_a_empty_retries is not None else config.parameters.get("stage_a_empty_retries",1)
    if type(empty_retries) is not int or not 0<=empty_retries<=2:
        raise ValueError("stage_a_empty_retries must be an integer between zero and two")
    evidence_retries=config.parameters.get("stage_b_evidence_retries",1)
    if type(evidence_retries) is not int or evidence_retries not in {0,1}:
        raise ValueError("stage_b_evidence_retries must be integer zero or one")
    sources=document_sources or [{"source_id":"main","text":text,"role":"main"}]
    blocks=[];offset=0
    for source in sources:
        source_windows=source_blocks(source["text"],chunk_chars,source_id=source["source_id"],base_offset=offset)
        if source.get("article_boundary_hint"):
            for window in source_windows:window["article_boundary_hint"]=source["article_boundary_hint"]
        blocks.extend(source_windows)
        offset+=len(source["text"])
    # B sees same original neighboring source windows in both variants. Its access
    # does not depend on A's presence or selected candidate navigation.
    for i,block in enumerate(blocks):
        review_segments=[]
        for neighbor in blocks[max(0,i-1):i+2]:
            if neighbor["source_id"]==block["source_id"]:
                review_segments.extend(neighbor["segments"])
        block["review_segments"]=review_segments
    pack,examples=parameter_context(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    _, navigation_terms = coverage_policy(config)
    if navigation_terms:
        navigation = search_evidence(sources, navigation_terms, limit=20)
        (output_dir / "evidence_navigation.json").write_text(json.dumps(navigation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidates, records, dispositions = [], [], []
    coverage = {"record_id": record_id, "source_sha256": hashlib.sha256(json.dumps([{ "source_id":v["source_id"], "text":v["text"]} for v in sources],sort_keys=True).encode()).hexdigest(),
                "variant": ablation, "prompt_version":CODING_PROMPT_VERSION,"status": "running", "stage_a_calls": 0, "stage_b_calls": 0,
                "domain_guide_version": "1", "domain_guide_sha256": DOMAIN_GUIDE_SHA256,
                "completeness_audit_version": AUDIT_VERSION,
                "stage_a_empty_retries":empty_retries,"stage_a_passes":[],
                "evidence_correction_version":"coding_v3","stage_b_evidence_retries":evidence_retries,"stage_b_evidence_calls":0,
                "sources":[{"source_id":v["source_id"],"role":v.get("role","supplement"),"sha256":hashlib.sha256(v["text"].encode()).hexdigest()} for v in sources],
                "blocks": [{k: v for k, v in b.items() if k not in {"text","segments","review_segments"}} for b in blocks], "completed_blocks": []}
    def save():
        (output_dir/"coverage.json").write_text(json.dumps(coverage, indent=2)+"\n")
        for name, rows in (("evidence_candidates.jsonl", candidates), ("coding_estimates.jsonl", records), ("candidate_dispositions.jsonl", dispositions)):
            (output_dir/name).write_text("".join(json.dumps(r, ensure_ascii=False, default=str)+"\n" for r in rows))
    save()
    try:
        for block in blocks:
            scoped = []
            user = json.dumps({"coding_task":coding_task_context(config),"record_id": record_id, "pmid": pmid, "source_block_id": block["block_id"], "coverage": "one block of a complete declared source; not the entire report", "parameters": config.parameters, "codebook_notes": config.notes, "source_segments": _stage_source(block), "synthetic_examples_guidance_only": examples}, ensure_ascii=False)
            if block.get("article_boundary_hint"):
                payload=json.loads(user);payload["article_scope_instruction"]=block["article_boundary_hint"]
                user=json.dumps(payload,ensure_ascii=False)
            fields = generate_field_descriptions(config, serialization=None)
            if ablation != "without_a":
                for pass_index in range(empty_retries+1):
                    coverage["stage_a_calls"] += 1
                    pass_audit={"block_id":block["block_id"],"pass_index":pass_index,
                                "purpose":"candidate_discovery" if pass_index==0 else "empty_candidate_rescan",
                                "backend":"langextract" if extract_a else "llm","status":"running"}
                    coverage["stage_a_passes"].append(pass_audit)
                    save()
                    try:
                        if extract_a:
                            candidate_config = copy.deepcopy(config)
                            if block.get("article_boundary_hint"):candidate_config.parameters["article_scope_instruction"]=block["article_boundary_hint"]
                            candidate_config.prompt.system = SEMANTICS+pack+A_SEMANTICS+(A_EMPTY_RULES if pass_index else "")
                            # Packaged A rules define this responsibility once;
                            # a generic "analysis later" preamble weakens scope.
                            candidate_config.prompt.user_preamble = ""
                            candidate_config.prompt.output_rules = "Use only the backend envelope; original values and source-grounded field evidence."
                            raw = extract_a({**block,"candidate_pass":pass_index},candidate_config)
                        else:
                            pass_user=json.loads(user);pass_user["candidate_pass"]=pass_index
                            raw = _candidate_records(_json(invoke("stage_a", [{"role":"system", "content":SEMANTICS+pack+A_RULES+(A_EMPTY_RULES if pass_index else "")+fields}, {"role":"user", "content":json.dumps(pass_user,ensure_ascii=False)}])))
                        if not isinstance(raw,list):raise ValueError("Stage A must return a JSON array")
                        pass_audit.update(status="candidates" if raw else "empty",candidate_count=len(raw))
                    except Exception as exc:
                        pass_audit.update(status="failed",error_type=type(exc).__name__)
                        save()
                        raise
                    save()
                    if raw:break
                coverage.setdefault("empty_candidate_checks",[]).append({
                    "block_id":block["block_id"],"initial_empty":pass_audit["pass_index"]>0 or not raw,
                    "passes":pass_index+1,"outcome":"recovered_candidates" if pass_index and raw else "still_empty" if not raw else "initial_candidates",
                    "scientific_absence_verified":False})
                for index, value in enumerate(raw):
                    row = _validated(value, config, block, pmid)
                    cid=json.dumps({"report":record_id,**_evidence_identity(row,[f.name for f in config.fields]+list(IDENTITY_FIELDS))},sort_keys=True,default=str)
                    row["candidate_id"] = "candidate:"+hashlib.sha256(cid.encode()).hexdigest()[:24]
                    row["producer"] = "stage_a"
                    scoped.append(row)
                scoped=list({r["candidate_id"]:r for r in scoped}.values())
                candidates.extend(scoped)
                save()
            if ablation == "without_b":
                for row in scoped:
                    records.append({**row, "semantic_review": "not_run", "ablation": ablation})
            else:
                coverage["stage_b_calls"] += 1
                review_block={**block,"segments":block["review_segments"]}
                review_user=json.loads(user);review_user.pop("synthetic_examples_guidance_only",None)
                review_user["stage_b_output_contract"]={"required_arrays":["records","dispositions"],"disposition_fields":["candidate_id","action","reason"]}
                b_system=B_SERIALIZATION+SEMANTICS+pack+B_RULES+fields+B_SERIALIZATION
                review_user["source_segments"]=_stage_source(review_block)
                review_user["source_catalog"]=[{"block_id":b["block_id"],"source_id":b["source_id"],"preview":b["text"][:240]} for b in blocks]
                parse_error=None
                for request_round in range(3):
                    if request_round:coverage["stage_b_calls"]+=1
                    raw_b=invoke("stage_b", [{"role":"system", "content":b_system}, {"role":"user", "content":json.dumps(review_user,ensure_ascii=False)+"\nCandidates (guidance only):\n"+json.dumps(scoped,ensure_ascii=False)}])
                    try:
                        payload=_json(raw_b)
                    except ValueError as exc:
                        parse_error=exc
                        payload={"malformed_response":raw_b}
                        break
                    requested=payload.get("request_block_ids",[]) if isinstance(payload,dict) else []
                    if not requested:break
                    if not isinstance(requested,list) or len(requested)>2 or len(set(requested))!=len(requested):
                        raise ValueError("B may request at most two distinct source blocks per round")
                    lookup={b["block_id"]:b for b in blocks}
                    if any(bid not in lookup for bid in requested):raise ValueError("Unknown requested source block")
                    review_block["segments"]=review_block["segments"]+[segment for bid in requested for segment in lookup[bid]["segments"]]
                    review_user["source_segments"]=_stage_source(review_block)
                    coverage.setdefault("source_requests",[]).append({"origin_block":block["block_id"],"requested":requested})
                    save()
                else:
                    raise ValueError("B source-request budget exhausted before final review")
                try:
                    if parse_error is not None:raise parse_error
                    block_records,ds=_validate_b_contract(payload,scoped,config,review_block,pmid,ablation)
                except ValueError as contract_error:
                    # One same-source, same-candidate repair. No A rerun, automatic
                    # ID filling, action changes, or unbounded source-query loop.
                    feedback=_b_contract_feedback(payload,scoped,contract_error)
                    audit={"block_id":block["block_id"],"attempts":1,"status":"running",**feedback}
                    coverage.setdefault("stage_b_contract_corrections",[]).append(audit)
                    coverage["stage_b_calls"]+=1
                    save()
                    correction_user={**review_user,"candidate_contract_feedback":feedback,
                        "invalid_response":payload,
                        "correction_task":"Correct the declared JSON structure and candidate association once using exactly the same source and candidates. Copy each supplied candidate_id into its corresponding record; never guess an association, invent a new ID, delete a candidate, or change an existing disposition action to escape validation. Preserve source-supported estimate values. Every existing legal disposition action is locked and must remain unchanged. If a locked keep/correct/pending record cannot be associated confidently, leave the repair unsuccessful rather than guessing a pairing. Only candidates whose action was missing or invalid may be marked pending based on the same source. No additional source request or further correction is available."}
                    try:
                        corrected=_json(invoke("stage_b",[{"role":"system","content":b_system},
                            {"role":"user","content":json.dumps(correction_user,ensure_ascii=False)+"\nCandidates (guidance only):\n"+json.dumps(scoped,ensure_ascii=False)}]))
                        block_records,ds=_validate_b_contract(corrected,scoped,config,review_block,pmid,ablation,
                            locked_actions=feedback["locked_disposition_actions"])
                        payload=corrected
                        audit["status"]="corrected"
                    except Exception as exc:
                        audit.update(status="failed",error_type=type(exc).__name__,final_validation_error=str(exc))
                        save()
                        raise
                targets=_unlocated_evidence_targets(payload,block_records) if evidence_retries else []
                if targets:
                    audit={"block_id":block["block_id"],"status":"running","logical_calls":1,
                           "source_segments_sha256":_data_sha256(_stage_source(review_block)),
                           "original_payload_sha256":_data_sha256(payload),"targets":targets,
                           "provider_attempts":"Each transport attempt remains in stage_b llm_calls.jsonl under request_sha256"}
                    coverage.setdefault("stage_b_evidence_corrections",[]).append(audit)
                    coverage["stage_b_calls"]+=1;coverage["stage_b_evidence_calls"]+=1
                    correction={"operation":"evidence_only_correction","source_segments":_stage_source(review_block),
                                "readonly_payload":payload,"targets":[{k:v for k,v in t.items() if k!="evidence_key"} for t in targets],
                                "program_flags":[{"record_index":i,"review_flags":r.get("review_flags",[])} for i,r in enumerate(block_records)]}
                    messages=[{"role":"system","content":B_EVIDENCE_RULES},{"role":"user","content":json.dumps(correction,ensure_ascii=False)}]
                    audit["request_sha256"]=_data_sha256(messages)
                    save()
                    try:
                        raw_patch=invoke("stage_b",messages)
                        audit["raw_patch_response"]=raw_patch
                        patched=_apply_evidence_patches(payload,_json(raw_patch),targets)
                        repaired,repaired_ds=_validate_b_contract(patched,scoped,config,review_block,pmid,ablation)
                        unresolved=[]
                        for target in targets:
                            checked=repaired[target["record_index"]];field=target["field"]
                            quotes=checked.get("field_evidence",{}).get(field,[])
                            if not quotes or any(q.get("ambiguous") for q in quotes) or "numeric_value_not_in_evidence:"+field in checked.get("review_flags",[]):
                                unresolved.append({"record_index":target["record_index"],"field":field})
                        audit["remaining_unresolved_targets"]=unresolved
                        if unresolved:
                            audit["status"]="unresolved_original_retained"
                        else:
                            block_records,ds=repaired,repaired_ds
                            audit.update(status="evidence_located",patched_payload_sha256=_data_sha256(patched),
                                         remaining_review_flags=[r.get("review_flags",[]) for r in repaired])
                    except Exception as exc:
                        # Optional correction failures retain the already valid
                        # semantic response and its pending grounding flags.
                        audit.update(status="failed_original_retained",error_type=type(exc).__name__,error=str(exc))
                    save()
                records.extend(block_records)
                dispositions.extend(ds)
            coverage["completed_blocks"].append(block["block_id"])
            save()
        # Only identical fields AND identical original evidence anchors merge.
        # Values alone or numerical nearness never establish identity.
        names=[f.name for f in config.fields]+list(IDENTITY_FIELDS)
        unique={}
        for row in records:
            identity=json.dumps({"report":record_id,**_evidence_identity(row,names)},sort_keys=True,default=str)
            key=hashlib.sha256(identity.encode()).hexdigest()[:24]
            row["estimate_id"]="estimate:"+key
            if key in unique:
                unique[key].setdefault("duplicate_candidate_ids",[]).append(row.get("candidate_id"))
            else:unique[key]=row
        records[:]=unique.values()
        audit = audit_completeness(sources, records, candidates, dispositions, config, blocks, coverage["completed_blocks"])
        (output_dir / "completeness.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending_signals = [signal for signal in audit["signals"] if signal["status"] == "unresolved_source_signal"]
        for row in records:
            # The document may contain an additional source-reported estimate.
            # Hold only outputs tied to that source/target for review; no signal
            # is promoted to an eligible record and no missing value is inferred.
            if any(attributable_pending_signal(signal, row, config) for signal in pending_signals):
                row["review_flags"] = sorted(set(row.get("review_flags", []) + ["coverage_unresolved_estimate_signal"]))
                row["needs_review"] = True
                if row.get("semantic_review") == "reviewed":
                    row["semantic_review"] = "pending"
        coverage["completeness"] = {key: audit[key] for key in ("audit_version", "status", "signal_count", "unresolved_signal_count", "source_processing_complete")}
        coverage["completeness_path"] = str(output_dir / "completeness.json")
        coverage["status"] = "complete"
        save()
        return records
    except Exception as exc:
        coverage.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save()
        raise
