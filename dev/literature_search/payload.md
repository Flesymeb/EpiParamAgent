```json
{
  "research_question": "I want to perform a meta-analysis of COVID-19 serial intervals.",
  "domain": "infectious_disease",
  "params": {
    "use_scoping": true,
    "scoping_providers": ["tavily", "serper"],
    "scoping_max_results": 5,
    "pubmed_retmax": "all",
    "pubmed_date_range": "2020/1/1-2020/10/22",
    "use_llm_queries": true,
    "max_queries": 5,
    "include_medline_only": false
  }
}
```

```json
{
  "research_question": "I want to perform a meta-analysis of COVID-19 **isolation delay intervals**.",
  "domain": "infectious_disease",
  "params": {
    "use_scoping": true,
    "scoping_providers": ["tavily", "serper"],
    "scoping_max_results": 5,
    "pubmed_retmax": "all",
    "pubmed_date_range": "2020/1/1-2020/10/22",
    "use_llm_queries": true,
    "max_queries": 5,
    "include_medline_only": false
  }
}
```
