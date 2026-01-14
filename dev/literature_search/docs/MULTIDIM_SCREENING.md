# Multi-Dimensional Literature Screening

## Overview

This module implements a **multi-dimensional relevance scoring system** for screening epidemiological literature, moving beyond simple include/exclude decisions to enable flexible filtering and prioritization.

## Key Features

✅ **7-Dimension Evaluation Framework**

- Disease Relevance
- Original Empirical Data
- Population-Level Study
- Parameter Availability
- Statistical Usability
- Design Relevance
- Target-Parameter Alignment

✅ **Flexible Scoring** - HIGH / MEDIUM / LOW / UNCERTAIN for each dimension

✅ **Weighted Aggregation** - Configurable weights with overall 0-1 score

✅ **Structured Output** - LLM returns validated Pydantic models with rationales

✅ **Configurable Criteria** - Define evaluation criteria in YAML

## Quick Start

### 1. Enable Multi-Dimensional Screening

```python
from langgraph_pipeline.graph import build_graph, run_once

graph = build_graph().compile()

result = run_once(
    graph,
    research_question="What is the serial interval of COVID-19?",
    workdir="outputs/test_run",
    params={
        "llm_screen": True,
        "use_multidim_screening": True,  # Enable multi-dimensional mode
    }
)
```

### 2. Customize Evaluation Criteria

Edit `configs/screening_dimensions.yaml`:

```yaml
dimensions:
  - id: disease_relevance
    name: "Disease Relevance"
    weight: 0.20  # Adjust importance
    criteria_high: |
      - Explicitly studies COVID-19 epidemiology
      - Focuses on transmission parameters
    # ... customize criteria for your domain
```

### 3. Access Dimension Scores

Results include detailed dimension scores for each paper:

```python
for paper in result["included"]:
    print(f"Title: {paper['title']}")
    print(f"Overall Score: {paper['overall_score']:.2f}")
    print(f"Recommendation: {paper['screen_decision']}")
    print(f"Dimension Scores: {paper['dimension_scores']}")
    print(f"Rationales: {paper['dimension_rationales']}")
```

## Output Format

### Record Structure

```json
{
  "id": "PMID:32637423",
  "title": "...",
  "abstract": "...",
  "screen_decision": "include",
  "overall_score": 0.85,
  "confidence": 0.92,
  "dimension_scores": {
    "disease_relevance": "HIGH",
    "original_data": "HIGH",
    "population_level": "MEDIUM",
    "parameter_availability": "HIGH",
    "statistical_usability": "HIGH",
    "design_relevance": "MEDIUM",
    "parameter_alignment": "HIGH"
  },
  "dimension_rationales": {
    "disease_relevance": "Directly addresses COVID-19 serial interval estimation",
    "original_data": "Uses contact tracing data from Hong Kong outbreak",
    ...
  }
}
```

### CSV Export

Dimension scores are automatically flattened into columns:

```
id,title,year,overall_score,dim_disease_relevance,dim_original_data,...
PMID:123,Study Title,2020,0.85,HIGH,HIGH,MEDIUM,HIGH,HIGH,MEDIUM,HIGH
```

## Configuration

### Dimension Weights

Adjust in `configs/screening_dimensions.yaml`:

```yaml
dimensions:
  - id: disease_relevance
    weight: 0.20  # Critical dimensions get higher weight
  - id: original_data
    weight: 0.20  # Critical
  - id: population_level
    weight: 0.15  # Important
  # ... sum should equal 1.0
```

### Decision Thresholds

```yaml
aggregation:
  thresholds:
    include: 0.70   # Score >= 0.70 → INCLUDE
    maybe: 0.40     # 0.40-0.70 → MAYBE (manual review)
    exclude: 0.40   # Score < 0.40 → EXCLUDE

  critical_exclusions:
    - dimension: disease_relevance
      condition: "LOW"
      action: "EXCLUDE"  # Override score if disease relevance is LOW
```

## API Reference

### EpiDimensionScores

Pydantic model for dimension scoring:

```python
from screening.dimension_scoring import EpiDimensionScores

scores = EpiDimensionScores(
    disease_relevance="HIGH",
    original_data="HIGH",
    population_level="MEDIUM",
    parameter_availability="HIGH",
    statistical_usability="HIGH",
    design_relevance="MEDIUM",
    parameter_alignment="HIGH",
    rationales={
        "disease_relevance": "COVID-19 epidemiology study",
        # ...
    }
)

# Calculate weighted score
scores.calculate_overall_score()
print(scores.overall_score)  # 0.825

# Get recommendation
scores.calculate_recommendation()
print(scores.recommendation)  # "INCLUDE"

# Get summary
summary = scores.get_dimension_summary()
failed = scores.get_failed_dimensions()  # ["dimension1", ...]
high = scores.get_high_dimensions()  # ["dimension2", ...]
```

### Dimension Loader

```python
from screening.dimension_loader import load_and_format_dimensions

# Load and format dimensions for prompt
formatted_text, weights, aggregation = load_and_format_dimensions(
    yaml_path=Path("configs/screening_dimensions.yaml"),
    include_weights=False
)

# Use in custom workflows
from screening.dimension_loader import load_dimensions_from_yaml

config = load_dimensions_from_yaml()
dimensions = config["dimensions"]
for dim in dimensions:
    print(f"{dim['name']}: weight={dim['weight']}")
```

## Binary vs Multi-Dimensional Screening

### Binary Mode (Default)

```python
result = run_once(
    graph,
    llm_screen=True,
    use_multidim_screening=False  # or omit
)
# Output: screen_decision = "include" | "exclude"
```

### Multi-Dimensional Mode

```python
result = run_once(
    graph,
    llm_screen=True,
    use_multidim_screening=True
)
# Output: screen_decision = "include" | "maybe" | "exclude"
#         + dimension_scores, overall_score, rationales
```

## Best Practices

1. **Start with defaults**: Test with default criteria before customizing
2. **Adjust weights**: Prioritize dimensions critical for your meta-analysis
3. **Use MAYBE category**: Papers with 0.40-0.70 scores deserve manual review
4. **Check confidence**: Low confidence (<0.7) may indicate ambiguous abstracts
5. **Iterate criteria**: Refine criteria based on screening results

## Examples

See `examples/multidim_screening_example.py` for complete workflow.

## Troubleshooting

**Q: LLM returns invalid JSON**

- A: Structured output with Pydantic should prevent this. If it fails, the system falls back to binary mode.

**Q: Weights don't sum to 1.0**

- A: Check `configs/screening_dimensions.yaml`. The system will warn but not fail.

**Q: All papers score MEDIUM**

- A: Refine criteria to be more specific. Check that HIGH/LOW criteria are clearly distinguished.

**Q: Want to use custom criteria file**

- A: Pass `screening_dimensions_path` parameter or modify default config location.

## Development

Created files:

- `src/screening/dimension_scoring.py` - Pydantic models
- `src/screening/dimension_loader.py` - Config loader
- `configs/screening_dimensions.yaml` - Criteria definitions
- `langgraph_pipeline/prompts/multidim_screening.md` - LLM prompt
- Updated: `langgraph_pipeline/nodes.py` - Screening logic
- Updated: `src/epidemiology/utils.py` - Export with dimensions
