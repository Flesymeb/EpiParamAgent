"""Build reproducible PubMed queries from review-level concepts."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metaagent.config import load_llm_config


class PubMedQueryRequest(BaseModel):
    """Validated inputs collected by the PubMed query wizard."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=5)
    disease: str = Field(min_length=2)
    parameter: str = Field(min_length=2)
    start_date: date
    end_date: date
    project_id: str = "p1"

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_iso_date(cls, value: object) -> date:
        """Parse one strict ISO calendar date."""
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError("Dates must use YYYY-MM-DD format") from exc

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, value: object) -> str:
        """Normalize a review identifier to the p-prefixed form."""
        text = str(value or "p1").strip().lower()
        if text.isdigit():
            text = f"p{text}"
        if not re.fullmatch(r"p[a-z0-9_-]+", text):
            raise ValueError("Project ID must start with p and contain letters, numbers, _ or -")
        return text

    @model_validator(mode="after")
    def validate_date_order(self) -> PubMedQueryRequest:
        """Reject publication windows with reversed boundaries."""
        if self.start_date > self.end_date:
            raise ValueError("Start date must be before or equal to end date")
        return self


class PubMedQueryTerms(BaseModel):
    """Disease and parameter vocabulary proposed by the LLM."""

    model_config = ConfigDict(str_strip_whitespace=True)

    disease_keywords: list[str] = Field(default_factory=list)
    disease_mesh_terms: list[str] = Field(default_factory=list)
    parameter_keywords: list[str] = Field(default_factory=list)
    parameter_mesh_terms: list[str] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "disease_keywords",
        "disease_mesh_terms",
        "parameter_keywords",
        "parameter_mesh_terms",
        "warnings",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[object]:
        """Accept common single-string responses from compatible LLM APIs."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        raise ValueError("Expected a string or list of strings")


class PubMedQueryArtifact(BaseModel):
    """Serializable record of a generated PubMed query."""

    schema_version: str = "1.0"
    created_at: datetime
    provider: str
    model: str
    request: PubMedQueryRequest
    terms: PubMedQueryTerms
    query: str


def _safe_term(value: str) -> str:
    text = re.sub(r"\[[^\]]+\]", "", str(value or ""))
    text = text.replace('"', " ").replace("(", " ").replace(")", " ")
    text = re.sub(r"\s+", " ", text).strip(" ,;:")
    if re.search(r"\s(?:AND|OR|NOT)\s", text):
        return ""
    return text


def _dedupe_terms(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = _safe_term(value)
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        result.append(term)
        if len(result) >= limit:
            break
    return result


def _tagged_group(keywords: list[str], mesh_terms: list[str]) -> str:
    tagged = [f'"{term}"[Title/Abstract]' for term in keywords]
    tagged.extend(f'"{term}"[MeSH Terms]' for term in mesh_terms)
    if not tagged:
        raise ValueError("Each PubMed concept requires at least one searchable term")
    return "(" + " OR ".join(tagged) + ")"


def build_pubmed_query(
    request: PubMedQueryRequest,
    terms: PubMedQueryTerms,
) -> str:
    """Build a field-tagged query with a deterministic publication-date filter."""
    disease_keywords = _dedupe_terms(
        [request.disease, *terms.disease_keywords],
        limit=12,
    )
    disease_mesh = _dedupe_terms(terms.disease_mesh_terms, limit=6)
    parameter_keywords = _dedupe_terms(
        [request.parameter, *terms.parameter_keywords],
        limit=12,
    )
    parameter_mesh = _dedupe_terms(terms.parameter_mesh_terms, limit=6)

    disease_group = _tagged_group(disease_keywords, disease_mesh)
    parameter_group = _tagged_group(parameter_keywords, parameter_mesh)
    start = request.start_date.strftime("%Y/%m/%d")
    end = request.end_date.strftime("%Y/%m/%d")
    date_group = f"({start}:{end}[pdat])"
    return f"{disease_group} AND {parameter_group} AND {date_group}"


def _slug(value: str) -> str:
    text = re.sub(r"[^\w]+", "_", value.strip().casefold(), flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError("Disease and parameter must contain path-safe characters")
    return text


def default_output_dir(
    *,
    project_root: Path,
    disease: str,
    parameter: str,
    project_id: str,
) -> Path:
    """Return the standard local dataset directory for one review task."""
    normalized_project = PubMedQueryRequest.normalize_project_id(project_id)
    return (
        project_root
        / "dataset"
        / _slug(disease)
        / "screening"
        / _slug(parameter)
        / normalized_project
    )


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content or "")


def _parse_terms(response: Any) -> PubMedQueryTerms:
    text = _response_text(response).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The LLM did not return a JSON object")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"The LLM returned invalid JSON: {exc.msg}") from exc
    return PubMedQueryTerms.model_validate(payload)


class PubMedQueryGenerator:
    """Generate PubMed vocabulary with an OpenAI-compatible chat model."""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Create a lazy generator, optionally with an injected chat model."""
        self.llm = llm
        self.provider = provider or ("custom" if llm is not None else "")
        self.model = model or ("custom" if llm is not None else "")

    def _get_llm(self) -> Any:
        if self.llm is not None:
            return self.llm
        cfg = load_llm_config(
            {
                "llm_provider": self.provider or None,
                "llm_model": self.model or None,
            },
            module_hint="screening",
        )
        if not cfg.api_key:
            raise RuntimeError(
                "Missing screening LLM credentials. Configure SCREENING_LLM_PROVIDER "
                "and the provider API key in .env.local."
            )
        if not cfg.api_base:
            raise RuntimeError("Missing API base URL for the screening LLM provider")
        self.provider = cfg.provider or self.provider or "default"
        self.model = cfg.model or self.model or "unknown"
        http_client = httpx.Client(
            verify=cfg.verify_ssl,
            timeout=cfg.timeout_s,
        )
        self.llm = ChatOpenAI(
            model=self.model,
            temperature=cfg.temperature,
            api_key=cfg.api_key,
            base_url=cfg.api_base,
            max_tokens=min(cfg.max_tokens, 6000),
            max_retries=3,
            request_timeout=cfg.timeout_s,
            http_client=http_client,
        )
        return self.llm

    def generate(self, request: PubMedQueryRequest) -> PubMedQueryArtifact:
        """Generate retrieval terms and assemble a serializable query artifact."""
        system_prompt = (
            "You are a biomedical information specialist designing a high-recall "
            "PubMed search for an epidemiological systematic review. Expand only "
            "the disease and target-parameter concepts. Use standard English names, "
            "common abbreviations, historical names, and valid MeSH headings. Do not "
            "return Boolean operators, field tags, date clauses, or study-design filters "
            "inside individual terms. Parameter terms must be lexical synonyms or "
            "operationally equivalent labels for the exact requested parameter; do not "
            "substitute adjacent measures such as generic incidence, mortality, or "
            "attack rate unless the requested parameter explicitly includes them. MeSH "
            "terms must be exact or near-exact concept matches; omit uncertain broad "
            "headings. If no exact parameter MeSH heading exists, return an empty "
            "parameter_mesh_terms array instead of operational proxies. Return one "
            "JSON object only with these keys: "
            "disease_keywords, disease_mesh_terms, parameter_keywords, "
            "parameter_mesh_terms, rationale, warnings. Each term field must be a JSON "
            "array of concise strings; provide 4-8 title/abstract terms and up to 4 "
            "verified MeSH terms per concept."
        )
        user_prompt = (
            f"Research question: {request.question}\n"
            f"Disease: {request.disease}\n"
            f"Epidemiological parameter: {request.parameter}\n"
            f"Publication window: {request.start_date.isoformat()} to "
            f"{request.end_date.isoformat()}\n\n"
            "Generate retrieval vocabulary. Preserve sensitivity through true synonyms "
            "and historical names, not through broader neighboring outcomes."
        )
        bound_llm = self._get_llm().bind(response_format={"type": "json_object"})
        try:
            response = bound_llm.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
        except Exception as exc:
            root_cause = exc
            while root_cause.__cause__ is not None:
                root_cause = root_cause.__cause__
            detail = str(root_cause).strip() or root_cause.__class__.__name__
            raise RuntimeError(f"LLM query generation failed: {detail}") from exc
        terms = _parse_terms(response)
        return PubMedQueryArtifact(
            created_at=datetime.now(UTC),
            provider=self.provider,
            model=self.model,
            request=request,
            terms=terms,
            query=build_pubmed_query(request, terms),
        )


def save_query_artifact(
    artifact: PubMedQueryArtifact,
    output_dir: Path,
    *,
    force: bool = False,
) -> tuple[Path, Path]:
    """Atomically save query metadata and the copy-ready PubMed expression."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "query.json"
    text_path = output_dir / "query.txt"
    existing = [path for path in (json_path, text_path) if path.exists()]
    if existing and not force:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"Refusing to overwrite {names}; pass --force to replace them")

    json_tmp = output_dir / ".query.json.tmp"
    text_tmp = output_dir / ".query.txt.tmp"
    json_tmp.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    text_tmp.write_text(artifact.query + "\n", encoding="utf-8")
    json_tmp.replace(json_path)
    text_tmp.replace(text_path)
    return json_path, text_path


def search_pubmed_to_csv(
    query: str,
    output_file: Path,
    *,
    retmax: int | None,
    medline_only: bool = False,
) -> dict[str, int]:
    """Run the saved query and write screening-compatible PubMed metadata."""
    from tools.pubmed.client import PubMedClient

    client = PubMedClient(medline_only=medline_only)
    papers = client.search(query, retmax=retmax, year=None)
    fieldnames = [
        "PMID",
        "Title",
        "Authors",
        "Citation",
        "First Author",
        "Journal/Book",
        "Publication Year",
        "Create Date",
        "PMCID",
        "NIHMS ID",
        "DOI",
        "Abstract",
        "Keywords",
        "mesh_terms",
        "pub_types",
    ]
    rows: list[dict[str, Any]] = []
    for paper in papers:
        pmid = paper.id.removeprefix("pubmed:")
        published = paper.published if paper.published.year > 1900 else None
        journal = paper.journal_ref or ""
        citation_parts = [part for part in (journal, str(published.year) if published else "") if part]
        rows.append(
            {
                "PMID": pmid,
                "Title": paper.title,
                "Authors": ", ".join(paper.authors),
                "Citation": ". ".join(citation_parts),
                "First Author": paper.authors[0] if paper.authors else "",
                "Journal/Book": journal,
                "Publication Year": published.year if published else "",
                "Create Date": published.strftime("%Y/%m/%d") if published else "",
                "PMCID": "",
                "NIHMS ID": "",
                "DOI": paper.doi or "",
                "Abstract": paper.abstract,
                "Keywords": "",
                "mesh_terms": "",
                "pub_types": "",
            }
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "retrieved": len(rows),
        "total_matches": int(client.last_total or 0),
    }


__all__ = [
    "PubMedQueryRequest",
    "PubMedQueryArtifact",
    "PubMedQueryGenerator",
    "PubMedQueryTerms",
    "build_pubmed_query",
    "default_output_dir",
    "save_query_artifact",
    "search_pubmed_to_csv",
]
