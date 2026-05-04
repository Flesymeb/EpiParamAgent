from typing import List, Iterable, Optional, Dict, Any
from itertools import combinations, product
import json
import re
import logging
from pathlib import Path

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


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
        pubmed_field: str = "all",
    ):
        self.provider = provider if provider in self.provider_templates else "generic"
        self.max_queries = max_queries
        self.include_single_terms = include_single_terms
        self.apply_wildcards = apply_wildcards
        self.pubmed_field = (pubmed_field or "all").strip().lower()
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

    def _pubmed_field_tag(self) -> str:
        if self.pubmed_field == "tiab":
            return "[tiab]"
        return "[All Fields]"

    def _pubmed_token(self, token: str) -> str:
        return self._pubmed_token_with_tag(token, self._pubmed_field_tag())

    def _pubmed_token_with_tag(self, token: str, tag: str) -> str:
        token = token.strip().strip('"')
        if not token:
            return ""
        if "[" in token and token.endswith("]"):
            return token
        if "*" in token:
            return f"{token}{tag}"
        return f'"{token}"{tag}'

    def _pubmed_term(self, term: str) -> str:
        cleaned = term.strip().strip('"')
        if not cleaned:
            return cleaned
        if " " in cleaned:
            cleaned = cleaned.replace("-", " ")
            cleaned = " ".join(cleaned.split())
        parts = [p for p in cleaned.split() if p]
        if len(parts) <= 1:
            token = parts[0] if parts else ""
            return self._pubmed_token(token)
        if len(parts) == 2:
            phrase = " ".join(parts)
            return f'"{phrase}"{self._pubmed_field_tag()}'
        tagged = [self._pubmed_token(p) for p in parts]
        tagged = [t for t in tagged if t]
        if not tagged:
            return ""
        return "(" + " AND ".join(tagged) + ")"

    def _rewrite_pubmed_phrases(self, query: str) -> str:
        def _replace(match: re.Match) -> str:
            phrase = match.group(1)
            tag = match.group(2) or self._pubmed_field_tag()
            parts = [p for p in phrase.split() if p]
            if len(parts) <= 2:
                return match.group(0)
            tagged = [self._pubmed_token_with_tag(p, tag) for p in parts]
            tagged = [t for t in tagged if t]
            if not tagged:
                return match.group(0)
            return "(" + " AND ".join(tagged) + ")"

        return re.sub(r'"([^"]+)"(\[[^\]]+\])?', _replace, query)

    def _quote(self, term: str) -> str:
        term = self._normalize_term(term)
        if self.provider == "pubmed":
            return self._pubmed_term(term)
        if self.provider == "eric":
            parts = [p for p in term.split() if p]
            if len(parts) > 1:
                return "(" + " AND ".join(parts) + ")"
            return term

        # Avoid overly long phrases or hyphenated terms that cause errors.
        # "time between symptom onset" -> too long (4+ words)
        # "symptom-onset interval" -> hyphenated phrase
        parts = [p.strip() for p in term.split() if p.strip()]

        # If 4+ words, break into AND-connected terms instead of phrase
        if len(parts) >= 4:
            return "(" + " AND ".join(parts) + ")"

        # If contains hyphen in a multi-word phrase, remove hyphen and treat as phrase
        if " " in term and "-" in term:
            # Remove hyphens from multi-word phrases
            term = term.replace("-", " ")
            # Re-split and rejoin to normalize spaces
            term = " ".join(term.split())

        if " " in term:
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
        if self.provider == "pubmed":
            q = self._rewrite_pubmed_phrases(q)
        # If mixed AND/OR, ensure OR groups are parenthesized
        if " OR " in q and " AND " in q:
            parts = [p.strip() for p in q.split(" AND ")]
            fixed = []
            for part in parts:
                if " OR " in part and not (part.startswith("(") and part.endswith(")")):
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

        # CRITICAL: Validate structure before normalization
        validated = []
        for q in cleaned:
            if self._is_flat_or_structure(q):
                logger.warning(f"Rejecting flat OR query (too broad): {q[:100]}...")
                # Try to fix it
                fixed = self._fix_flat_or_query(q, keyword_set)
                if fixed:
                    validated.append(fixed)
            else:
                validated.append(q)

        if not validated:
            logger.warning(
                "All LLM queries rejected as flat OR. Generating fallback queries."
            )
            return self._generate_fallback_faceted_queries(keyword_set)

        normalized = [self._normalize_query(q) for q in validated]
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

    def _is_flat_or_structure(self, query: str) -> bool:
        """Detect if query is a flat OR list (disease OR action OR time OR ...)

        Bad pattern: More than 8 OR clauses in the outermost level
        """
        # Remove nested parentheses to check only top level
        import re

        # Count top-level OR operators (not inside nested parens)
        depth = 0
        top_level_ors = 0
        i = 0
        while i < len(query):
            if query[i] == "(":
                depth += 1
            elif query[i] == ")":
                depth -= 1
            elif depth == 0 and query[i : i + 3].upper() == " OR":
                top_level_ors += 1
                i += 2
            i += 1

        # If >8 OR at top level, likely flat structure
        return top_level_ors > 8

    def _fix_flat_or_query(self, query: str, keyword_set) -> Optional[str]:
        """Attempt to restructure flat OR into faceted AND

        Strategy: Group terms by category, then connect with AND
        """
        # This is a best-effort heuristic fix
        # In practice, it's better to regenerate
        return None  # Trigger fallback

    def _generate_fallback_faceted_queries(self, keyword_set) -> List[str]:
        """Generate simple faceted queries when LLM fails

        Structure: (Disease) AND (Action/Time)
        """
        queries = []

        # Extract core terms
        disease = (keyword_set.primary_keywords or [])[:2]
        disease_syn = (keyword_set.synonyms or [])[:2]
        disease_facet = self._or_group(disease + disease_syn)

        # Time/interval terms
        time_terms = []
        for term in keyword_set.primary_keywords or []:
            if any(
                t in term.lower()
                for t in ["delay", "interval", "time", "latency", "period"]
            ):
                time_terms.append(term)
        if not time_terms:
            time_terms = ["interval", "delay"]
        time_facet = self._or_group(time_terms[:3])

        # Action terms
        action_terms = []
        for term in (keyword_set.primary_keywords or []) + (
            keyword_set.related_terms or []
        ):
            if any(
                t in term.lower()
                for t in ["isolation", "quarantine", "diagnosis", "testing"]
            ):
                action_terms.append(term)
        action_facet = self._or_group(action_terms[:3]) if action_terms else None

        # Query 1: Disease AND Time AND Action
        if disease_facet and time_facet and action_facet:
            queries.append(self._and_join([disease_facet, time_facet, action_facet]))

        # Query 2: Disease AND Time (recall-focused)
        if disease_facet and time_facet:
            queries.append(self._and_join([disease_facet, time_facet]))

        # Query 3: Add study design
        if disease_facet and time_facet and action_facet:
            design = self._or_group((keyword_set.design_terms or [])[:3])
            if design:
                queries.append(
                    self._and_join([disease_facet, time_facet, action_facet, design])
                )

        return [self._format(q) for q in queries if q][: self.max_queries]

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

    def _add_wildcard_terms(
        self, terms: List[str], hints: Dict[str, List[str]]
    ) -> List[str]:
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
        iterations: int = 3,
        min_queries: int = 5,
        research_query: Optional[str] = None,
        prompt_hint: Optional[str] = None,
        term_groups: Optional[List[str]] = None,
        term_limits: Optional[Dict[str, int]] = None,
    ) -> List[str]:
        """Use an LLM (via provided `agent` which should implement `_call_llm`) to generate boolean queries.

        If `agent` is None or LLM call fails, falls back to `generate_queries` combinatorial method.
        """
        if agent is None:
            return self.generate_queries(keyword_set)

        all_groups = [
            "primary_keywords",
            "synonyms",
            "related_terms",
            "domain_terms",
            "outcome_terms",
            "design_terms",
            "population_terms",
            "measurement_terms",
            "context_terms",
        ]
        if term_groups:
            groups = [g for g in term_groups if g in all_groups]
        else:
            groups = list(all_groups)
        limits = term_limits or {}

        # Build prompt
        if prompt_hint is None:
            prompt_hint = self._load_prompt_hint()

        system = SystemMessage(
            content=(
                "You are an expert assistant that generates boolean search queries for academic databases (PubMed, MEDLINE).\n\n"
                "🚨 CRITICAL INSTRUCTION:\n"
                "You will receive a LARGE list of keywords (30-50 terms). DO NOT use all of them.\n"
                "Your task is to SELECT 5-10 terms and organize them into THEMATIC FACETS.\n\n"
                "FACETED QUERY STRUCTURE (MANDATORY):\n"
                "  Step 1: Identify 2-3 facets based on research topic\n"
                "  Step 2: Select 2-4 terms per facet (NOT all terms)\n"
                "  Step 3: Connect facets with AND\n\n"
                "EXAMPLE (Isolation Delay Research):\n"
                "  Facet 1 (Disease): COVID-19, SARS-CoV-2\n"
                "  Facet 2 (Time):    interval, delay, latenc*\n"
                "  Facet 3 (Action):  isolat*, quarantin*\n"
                "  Query: (COVID-19 OR SARS-CoV-2) AND (interval OR delay OR latenc*) AND (isolat* OR quarantin*)\n\n"
                "❌ WRONG (flat OR list using all 30+ terms):\n"
                "  (COVID-19 OR SARS-CoV-2 OR isolation OR delay OR interval OR quarantine OR symptom OR onset OR ...)\n\n"
                "SELECTION CRITERIA:\n"
                "  - primary_keywords: Use 2-3 MOST ESSENTIAL terms only\n"
                "  - synonyms: Pick 1-2 TRUE synonyms per facet\n"
                "  - related_terms: Use 0-2 if they define a separate facet\n"
                "  - design/population/outcome: Usually SKIP unless critical to topic\n\n"
                "WILDCARD USAGE:\n"
                "  - Use * to compress word families: isolat* (isolation, isolated, isolate)\n"
                "  - Reduces query length significantly\n\n"
                "PHRASE QUOTING:\n"
                '  - Quote ONLY standard medical terms: "symptom onset", "contact tracing"\n'
                "  - For measurement words (delay, time, interval) → use AND, not quotes\n\n"
                "OUTPUT FORMAT:\n"
                '  - Return ONLY valid JSON: {"queries": ["query1", "query2", ...]}\n'
                "  - Generate 3-5 queries with different facet combinations\n"
                "  - Each query: 2-3 facets, each facet: 2-4 terms\n"
                "  - Target query length: <250 characters\n\n"
                f"{prompt_hint or ''}"
            )
        )

        example: Dict[str, List[Any]] = {}
        for name in all_groups:
            values = list(getattr(keyword_set, name, []) or [])
            limit = limits.get(name, 10)
            if name not in groups:
                example[name] = []
            else:
                example[name] = values[:limit]

        context = ""
        if research_query:
            context += f"Research question: {research_query}\n"
        if prompt_hint:
            context += f"Guidance: {prompt_hint}\n"

        rubric = (
            "QUERY GENERATION PROCESS:\n\n"
            "Step 1: ANALYZE THE RESEARCH TOPIC\n"
            "  - What are the 2-3 core concepts?\n"
            "  - Example: 'COVID-19 isolation delay' → Disease + Time + Action\n\n"
            "Step 2: SELECT TERMS (DO NOT USE ALL)\n"
            "  From primary_keywords (5 terms) → Pick 2-3 MOST ESSENTIAL\n"
            "  From synonyms (7 terms) → Pick 1-2 per facet\n"
            "  From related_terms (10 terms) → Pick 0-2 if needed\n"
            "  From design/outcome/population → USUALLY SKIP (use only if critical)\n\n"
            "Step 3: ORGANIZE INTO FACETS\n"
            "  Facet 1 (Disease): (COVID-19 OR SARS-CoV-2)\n"
            "  Facet 2 (Time): (interval OR delay OR latenc*)\n"
            "  Facet 3 (Action): (isolat* OR quarantin*)\n\n"
            "Step 4: CONNECT WITH AND\n"
            "  Query: Facet1 AND Facet2 AND Facet3\n\n"
            "EXAMPLES OF CORRECT QUERIES:\n"
            "  ✓ (COVID-19 OR SARS-CoV-2) AND (interval OR delay) AND (isolat* OR quarantin*)\n"
            "  ✓ (COVID-19 OR SARS-CoV-2) AND (interval OR delay)\n"
            '  ✓ (COVID-19 OR SARS-CoV-2) AND (delay OR latenc*) AND (isolat* OR quarantin*) AND ("cohort study" OR surveillance)\n\n'
            "EXAMPLES OF WRONG QUERIES:\n"
            "  ✗ (COVID-19 OR SARS-CoV-2 OR isolation OR delay OR interval OR quarantine OR symptom OR onset OR diagnosis OR testing OR ...)\n"
            '  ✗ (COVID-19 OR SARS-CoV-2 OR "coronavirus disease 2019" OR "2019-nCoV" OR "severe acute respiratory syndrome coronavirus 2" OR ...)\n'
            "  → These use TOO MANY terms in flat OR structure\n\n"
            "QUERY VARIATIONS (3-5 queries):\n"
            "  Query 1: Disease AND Time AND Action (core, 3 facets)\n"
            "  Query 2: Disease AND Time (recall-focused, 2 facets)\n"
            "  Query 3: Disease AND Time AND Action AND StudyDesign (precision-focused, 4 facets)\n"
            "  Query 4: Use different synonym combinations\n"
            "  Query 5: Alternative facet angle (e.g., Disease AND Action AND Outcome)\n\n"
            "REMEMBER: You have 30+ keywords available. Use only 5-10 of them."
        )
        user = HumanMessage(
            content=(
                "Generate {n} boolean search queries optimized for {provider}.\n\n".format(
                    n=self.max_queries, provider=self.provider
                )
                + context
                + rubric
                + "\n\nKeywords available:\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
                + "\n\nReturn ONLY the JSON object with NO additional text:\n"
                + '{"queries": ["query1", "query2", ...]}'
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

                # Extract JSON with improved parsing
                import re

                # Try to extract JSON from markdown code blocks first
                fenced = re.search(
                    r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```",
                    content,
                    re.IGNORECASE,
                )

                if fenced:
                    payload_text = fenced.group(1)
                else:
                    # Try to find JSON object or array in the content
                    # Look for complete JSON structures (greedy to get full content)
                    obj_match = re.search(
                        r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", content, re.DOTALL
                    )
                    list_match = re.search(
                        r"\[(?:[^\[\]]|(?:\[[^\[\]]*\]))*\]", content, re.DOTALL
                    )

                    if obj_match:
                        payload_text = obj_match.group(0)
                    elif list_match:
                        payload_text = list_match.group(0)
                    else:
                        payload_text = content

                # Clean up common JSON formatting issues
                payload_text = payload_text.strip()
                # Remove trailing commas before closing brackets
                payload_text = re.sub(r",(\s*[}\]])", r"\1", payload_text)
                # Fix unescaped quotes in strings (basic attempt)
                # payload_text = re.sub(r'(?<!\\)"(?=.*")', r'\"', payload_text)

                # Parse JSON
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError as je:
                    # Try to extract just the queries array if JSON is malformed
                    queries_match = re.search(
                        r'"queries"\s*:\s*(\[[\s\S]*?\])', payload_text
                    )
                    if queries_match:
                        payload = {"queries": json.loads(queries_match.group(1))}
                    else:
                        raise je

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
                    raise ValueError(
                        f"Too few queries from LLM (got {len(cleaned)}, need {min_queries})"
                    )

                formatted = self._postprocess_queries(cleaned, keyword_set)
                if len(formatted) < min_queries:
                    raise ValueError(
                        f"Too few usable queries after normalization (got {len(formatted)}, need {min_queries})"
                    )
                return formatted
            except Exception as e:
                last_error = e
                # Self-reflection: ask for improvement using previous error
                error_msg = str(e)
                critique = (
                    f"The previous output had issues: {error_msg}. "
                    "Please fix formatting, ensure valid JSON, and produce a larger, "
                    "diverse set of boolean queries. Ensure AND/OR groups are parenthesized. "
                    "Return ONLY the JSON object, no additional text."
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
                        'Return only valid JSON with key \'queries\': ["query1", "query2", ...]'
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
