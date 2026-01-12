from typing import List, Iterable, Optional, Dict, Any
from itertools import combinations, product
import json
from pathlib import Path

from langchain_core.messages import SystemMessage, HumanMessage


DEFAULT_WILDCARD_MAP = {
    "math": "math*",
    "mathematics": "math*",
    "predict": "predict*",
    "predictive": "predict*",
    "prediction": "predict*",
    "trajectory": "traject*",
    "trajectories": "traject*",
    "traject": "traject*",
}


class BooleanSearchAgent:
    """Build boolean search queries from a KeywordSet-like object.

    Usage:
      agent = BooleanSearchAgent()
      queries = agent.generate_queries(keyword_set)
    """

    provider_templates = {
        "generic": "{q}",
        "pubmed": "({q})",
        "psycinfo": "({q})",
        "eric": "{q}",  # keep as-is; ERIC dislikes phrase wrapping
    }

    def __init__(
        self,
        provider: str = "generic",
        max_queries: int = 20,
        *,
        include_single_terms: bool = True,
        apply_wildcards: bool = False,
        wildcard_map: Optional[Dict[str, str]] = None,
    ):
        self.provider = provider if provider in self.provider_templates else "generic"
        self.max_queries = max_queries
        self.include_single_terms = include_single_terms
        self.apply_wildcards = apply_wildcards
        self.wildcard_map = (
            {k.lower(): v for k, v in (wildcard_map or {}).items()}
            if wildcard_map
            else DEFAULT_WILDCARD_MAP
        )

    def _format(self, q: str) -> str:
        return self.provider_templates[self.provider].format(q=q)

    def _supports_wildcards(self) -> bool:
        return self.provider in {"pubmed", "psycinfo", "generic", "eric"}

    def _normalize_term(self, term: str) -> str:
        cleaned = term.strip()
        if (
            self.apply_wildcards
            and self._supports_wildcards()
            and "*" not in cleaned
            and " " not in cleaned
        ):
            mapped = self.wildcard_map.get(cleaned.lower())
            if mapped:
                return mapped
        return cleaned

    def _quote(self, term: str) -> str:
        term = self._normalize_term(term)
        if self.provider == "eric":
            parts = [p for p in term.split() if p]
            if len(parts) > 1:
                return "(" + " AND ".join(parts) + ")"
            return term
        if " " in term or "-" in term:
            return f'"{term}"'
        return term

    def _or_group(self, terms: Iterable[str]) -> Optional[str]:
        terms = [t for t in terms if t]
        if not terms:
            return None
        return "(" + " OR ".join(self._quote(t) for t in terms) + ")"

    def _and_join(self, parts: Iterable[str]) -> str:
        parts = [p for p in parts if p]
        if len(parts) > 1:
            parts = [f"({p})" if " OR " in p else p for p in parts]
        return " AND ".join(parts)

    def _normalize_query(self, query: str) -> str:
        q = " ".join(query.strip().split())
        if not q:
            return q
        # If mixed AND/OR, ensure OR groups are parenthesized
        if " OR " in q and " AND " in q:
            parts = [p.strip() for p in q.split(" AND ")]
            fixed = []
            for part in parts:
                if " OR " in part and not (
                    part.startswith("(") and part.endswith(")")
                ):
                    fixed.append(f"({part})")
                else:
                    fixed.append(part)
            q = " AND ".join(fixed)
        # Wrap top-level OR group
        if " OR " in q and not (q.startswith("(") and q.endswith(")")):
            q = f"({q})"
        return q

    def _score_query(self, query: str, keyword_set) -> float:
        q = query.lower()
        keywords = (
            list(getattr(keyword_set, "primary_keywords", []) or [])
            + list(getattr(keyword_set, "synonyms", []) or [])
            + list(getattr(keyword_set, "related_terms", []) or [])
            + list(getattr(keyword_set, "domain_terms", []) or [])
            + list(getattr(keyword_set, "outcome_terms", []) or [])
            + list(getattr(keyword_set, "design_terms", []) or [])
            + list(getattr(keyword_set, "population_terms", []) or [])
            + list(getattr(keyword_set, "measurement_terms", []) or [])
            + list(getattr(keyword_set, "context_terms", []) or [])
        )
        if not keywords:
            return 0.0
        hits = 0
        for kw in keywords:
            kw = str(kw).lower().strip()
            if kw and kw in q:
                hits += 1
        coverage = hits / max(1, len(set(k.lower() for k in keywords if k)))
        length_penalty = 1.0 if len(q) <= 220 else 0.7
        and_bonus = 1.0 if " AND " in q else 0.9
        return coverage * length_penalty * and_bonus

    def _postprocess_queries(self, queries: List[str], keyword_set) -> List[str]:
        cleaned = [q for q in queries if isinstance(q, str) and q.strip()]
        normalized = [self._normalize_query(q) for q in cleaned]
        deduped: List[str] = []
        seen = set()
        for q in normalized:
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(q)
        scored = sorted(
            deduped,
            key=lambda q: self._score_query(q, keyword_set),
            reverse=True,
        )
        return [self._format(q) for q in scored][: self.max_queries]

    def _extract_content(self, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        content = getattr(response, "content", None)
        if content is not None:
            if isinstance(content, list):
                parts: List[str] = []
                for part in content:
                    if isinstance(part, dict):
                        if "text" in part:
                            parts.append(str(part["text"]))
                        elif "content" in part:
                            parts.append(str(part["content"]))
                        else:
                            parts.append(str(part))
                    else:
                        parts.append(str(part))
                return "".join(parts).strip()
            return str(content)
        if hasattr(response, "choices") and response.choices:
            try:
                choice = response.choices[0]
                msg = getattr(choice, "message", None)
                if msg is not None and getattr(msg, "content", None):
                    return str(msg.content)
                if getattr(choice, "text", None):
                    return str(choice.text)
            except Exception:
                pass
        return str(response)

    def _add_wildcard_terms(self, terms: List[str], hints: Dict[str, List[str]]) -> List[str]:
        if not self.apply_wildcards or not self._supports_wildcards():
            return terms
        lowered = [t.lower() for t in terms]
        extras: List[str] = []
        for wildcard, needles in hints.items():
            if any(any(n in t for n in needles) for t in lowered):
                extras.append(wildcard)
        for w in extras:
            if w not in terms:
                terms.append(w)
        return terms

    def _build_facet_queries(self, keyword_set) -> List[str]:
        def _take(name: str, limit: int) -> List[str]:
            return [
                str(t).strip()
                for t in (getattr(keyword_set, name, []) or [])[:limit]
                if str(t).strip()
            ]

        construct = (
            _take("primary_keywords", 6)
            + _take("synonyms", 4)
            + _take("related_terms", 4)
        )
        outcome = self._add_wildcard_terms(
            _take("outcome_terms", 6),
            {"math*": ["math", "mathematics"]},
        )
        design = self._add_wildcard_terms(
            _take("design_terms", 6),
            {
                "predict*": ["predict", "prediction", "predictive"],
                "traject*": ["traject", "trajectory", "trajectories"],
            },
        )
        population = _take("population_terms", 6)
        measurement = _take("measurement_terms", 4) or _take("domain_terms", 4)
        context = _take("context_terms", 4)

        def _group(terms: List[str]) -> Optional[str]:
            return self._or_group(terms)

        def _add(parts: Iterable[str], queries: List[str]) -> None:
            q = self._and_join([p for p in parts if p])
            if q:
                queries.append(self._format(q))

        queries: List[str] = []
        if construct and outcome and design:
            _add([_group(construct), _group(outcome), _group(design)], queries)
        if construct and outcome:
            _add([_group(construct), _group(outcome)], queries)
        if construct and design:
            _add([_group(construct), _group(design)], queries)
        if construct and population:
            _add([_group(construct), _group(population)], queries)
        if construct and measurement:
            _add([_group(construct), _group(measurement)], queries)
        if construct and context:
            _add([_group(construct), _group(context)], queries)
        return queries

    def generate_queries(self, keyword_set, strategy: str = "mixed") -> List[str]:
        """Generate boolean queries from `keyword_set`.

        keyword_set must provide attributes: `primary_keywords`, `synonyms`, `related_terms`, `domain_terms`.

        Strategies:
          - 'mixed' (default): single terms + pairwise primary+domain + primary OR synonyms groups
          - 'pairwise': pairwise combinations of primary keywords
          - 'combinatorial': more exhaustive combinations (use with caution)
        """
        prim = list(getattr(keyword_set, "primary_keywords", []) or [])
        syn = list(getattr(keyword_set, "synonyms", []) or [])
        dom = list(getattr(keyword_set, "domain_terms", []) or [])
        rel = list(getattr(keyword_set, "related_terms", []) or [])

        queries: List[str] = []

        facet_queries = self._build_facet_queries(keyword_set)
        if facet_queries:
            queries.extend(facet_queries)
            if len(queries) >= self.max_queries:
                return queries[: self.max_queries]

        # 1) Single primary keywords
        if self.include_single_terms:
            for k in prim:
                queries.append(self._format(self._quote(k)))
                if len(queries) >= self.max_queries:
                    return queries[: self.max_queries]

        # 2) primary OR synonyms group
        if syn and prim:
            for p in prim[:3]:
                or_group = self._or_group([p] + syn[:5])
                if or_group:
                    queries.append(self._format(or_group))
                if len(queries) >= self.max_queries:
                    return queries[: self.max_queries]

        # 3) combine primary with domain terms
        for p in prim[:5]:
            for d in dom[:5]:
                q = self._and_join([self._quote(p), self._quote(d)])
                queries.append(self._format(q))
                if len(queries) >= self.max_queries:
                    return queries[: self.max_queries]

        # 4) pairwise primary combos
        for a, b in combinations(prim, 2):
            q = self._and_join([self._quote(a), self._quote(b)])
            queries.append(self._format(q))
            if len(queries) >= self.max_queries:
                return queries[: self.max_queries]

        # 5) related terms combined with primary
        for p in prim[:3]:
            if rel:
                q = self._and_join([self._quote(p), self._or_group(rel[:4])])
                queries.append(self._format(q))
                if len(queries) >= self.max_queries:
                    return queries[: self.max_queries]

        # Truncate
        return queries[: self.max_queries]

    def generate_queries_using_llm(
        self,
        keyword_set,
        agent=None,
        iterations: int = 2,
        min_queries: int = 5,
        research_query: Optional[str] = None,
        prompt_hint: Optional[str] = None,
    ) -> List[str]:
        """Use an LLM (via provided `agent` which should implement `_call_llm`) to generate boolean queries.

        If `agent` is None or LLM call fails, falls back to `generate_queries` combinatorial method.
        """
        if agent is None:
            return self.generate_queries(keyword_set)

        # Build prompt
        if prompt_hint is None:
            prompt_hint = self._load_prompt_hint()

        system = SystemMessage(
            content=(
                "You are an assistant that generates boolean search queries for academic databases. "
                "Given categorized keyword lists, return a JSON object with key 'queries' mapping to a list of search strings. "
                f"{prompt_hint or ''}"
            )
        )

        example = {
            "primary_keywords": keyword_set.primary_keywords[:10],
            "synonyms": keyword_set.synonyms[:10],
            "related_terms": keyword_set.related_terms[:10],
            "domain_terms": keyword_set.domain_terms[:10],
            "outcome_terms": getattr(keyword_set, "outcome_terms", [])[:10],
            "design_terms": getattr(keyword_set, "design_terms", [])[:10],
            "population_terms": getattr(keyword_set, "population_terms", [])[:10],
            "measurement_terms": getattr(keyword_set, "measurement_terms", [])[:10],
            "context_terms": getattr(keyword_set, "context_terms", [])[:10],
        }

        context = ""
        if research_query:
            context += f"Research question: {research_query}\n"
        if prompt_hint:
            context += f"Guidance: {prompt_hint}\n"

        rubric = (
            "Rubric: queries must be valid boolean logic, include at least one core term, "
            "avoid being overly broad, and cover different aspects (population/construct/method)."
        )
        user = HumanMessage(
            content=(
                "Generate up to {n} boolean search queries optimized for {provider}. "
                "Return only valid JSON with key 'queries'.\n\n".format(
                    n=self.max_queries, provider=self.provider
                )
                + context
                + rubric
                + "\nKeywords:\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
            )
        )

        last_error = None
        last_queries: List[str] = []
        for attempt in range(iterations):
            try:
                resp = agent._call_llm([system, user])
                content = self._extract_content(resp).strip()
                if not content:
                    raise ValueError("Empty LLM response")
                # extract JSON
                import re

                fenced = re.search(
                    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
                    content,
                    re.DOTALL | re.IGNORECASE,
                )
                payload_text = fenced.group(1) if fenced else content
                obj_match = re.search(r"\{.*?\}", payload_text, re.DOTALL)
                list_match = re.search(r"\[.*?\]", payload_text, re.DOTALL)
                if obj_match:
                    payload = json.loads(obj_match.group(0))
                elif list_match:
                    payload = json.loads(list_match.group(0))
                else:
                    payload = json.loads(payload_text)

                if isinstance(payload, list):
                    queries = payload
                else:
                    queries = payload.get("queries") or payload.get("search_queries")
                if not isinstance(queries, list):
                    raise ValueError("LLM did not return a list of queries")

                # Basic quality checks
                cleaned = [q for q in queries if isinstance(q, str) and q.strip()]
                last_queries = cleaned
                if len(cleaned) < min_queries:
                    raise ValueError("Too few queries from LLM")

                formatted = self._postprocess_queries(cleaned, keyword_set)
                if len(formatted) < min_queries:
                    raise ValueError("Too few usable queries after normalization")
                return formatted
            except Exception as e:
                last_error = e
                # Self-reflection: ask for improvement using previous error
                critique = (
                    "The previous output had issues. "
                    "Please fix formatting, ensure valid JSON, and produce a larger, "
                    "diverse set of boolean queries. Ensure AND/OR groups are parenthesized."
                )
                if last_queries:
                    critique += " Previous queries: " + "; ".join(last_queries[:5])
                if research_query:
                    critique += f" Research question: {research_query}."
                if prompt_hint:
                    critique += f" Guidance: {prompt_hint}."
                user = HumanMessage(
                    content=(
                        f"{critique}\n\n"
                        "Return only valid JSON with key 'queries'."
                    )
                )

        # Log and fallback
        try:
            import logging

            logging.getLogger(__name__).warning(
                f"LLM boolean generation failed after {iterations} attempts, falling back: {last_error}"
            )
        except Exception:
            pass
        return self.generate_queries(keyword_set)

    def _load_prompt_hint(self) -> Optional[str]:
        """Load provider-specific prompt hint from prompts directory if present."""
        prompt_dir = Path(__file__).parent / "prompts"
        provider_name = self.provider.lower()
        candidates = [
            prompt_dir / f"{provider_name}_boolean.md",
            prompt_dir / f"{provider_name}_boolean.txt",
        ]
        for path in candidates:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:
                    continue
        return None
