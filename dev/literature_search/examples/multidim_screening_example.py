"""Example: Multi-dimensional screening for COVID-19 epidemiology papers.

This script demonstrates how to use the multi-dimensional relevance scoring
system for literature screening.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph_pipeline.graph import build_graph, run_once
from screening.dimension_scoring import EpiDimensionScores
from screening.dimension_loader import load_and_format_dimensions


def example_basic_usage():
    """Basic usage: Run pipeline with multi-dimensional screening."""
    print("=" * 80)
    print("Example 1: Basic Multi-Dimensional Screening")
    print("=" * 80)

    graph = build_graph().compile()

    result = run_once(
        graph,
        research_question="What is the serial interval of COVID-19?",
        domain="epidemiology",
        workdir="outputs/multidim_example",
        params={
            "llm_screen": True,
            "use_multidim_screening": True,  # Enable multi-dimensional mode
            "min_year": 2020,
            "max_articles": 50,
        },
    )

    print(f"\n✅ Screening complete!")
    print(f"   Total records: {len(result.included) + len(result.excluded)}")
    print(f"   Included: {len(result.included)}")
    print(f"   Excluded: {len(result.excluded)}")

    # Show top 3 papers by score
    included = sorted(
        result.included,
        key=lambda x: x.get("overall_score", 0),
        reverse=True,
    )

    print("\n📊 Top 3 papers by relevance score:")
    for i, paper in enumerate(included[:3], 1):
        print(f"\n{i}. {paper.get('title', 'No title')[:80]}...")
        print(f"   Score: {paper.get('overall_score', 0):.2f}")
        print(f"   Decision: {paper.get('screen_decision', 'N/A')}")

        if "dimension_scores" in paper:
            dims = paper["dimension_scores"]
            high_dims = [k for k, v in dims.items() if v == "HIGH"]
            print(f"   HIGH dimensions: {', '.join(high_dims)}")


def example_inspect_dimensions():
    """Inspect dimension configuration."""
    print("\n" + "=" * 80)
    print("Example 2: Inspect Dimension Configuration")
    print("=" * 80)

    formatted_text, weights, aggregation = load_and_format_dimensions()

    print("\n📋 Configured Dimensions:")
    for dim_name, weight in weights.items():
        print(f"   {dim_name}: {weight:.2f}")

    print(f"\n⚙️ Aggregation Settings:")
    print(f"   Method: {aggregation.get('method')}")
    thresholds = aggregation.get("thresholds", {})
    print(f"   Include threshold: {thresholds.get('include', 0.70)}")
    print(f"   Maybe threshold: {thresholds.get('maybe', 0.40)}")

    print(f"\n🚫 Critical Exclusions:")
    for rule in aggregation.get("critical_exclusions", []):
        print(f"   - {rule['dimension']} == {rule['condition']} → {rule['action']}")


def example_manual_scoring():
    """Example: Manually score a paper."""
    print("\n" + "=" * 80)
    print("Example 3: Manual Paper Scoring")
    print("=" * 80)

    # Simulate LLM output
    scores = EpiDimensionScores(
        disease_relevance="HIGH",
        original_data="HIGH",
        population_level="MEDIUM",
        parameter_availability="HIGH",
        statistical_usability="HIGH",
        design_relevance="MEDIUM",
        parameter_alignment="HIGH",
        rationales={
            "disease_relevance": "Directly addresses COVID-19 serial interval",
            "original_data": "Uses contact tracing data from outbreak investigation",
            "population_level": "Small cohort study (n=100 transmission pairs)",
            "parameter_availability": "Reports serial interval mean and 95% CI",
            "statistical_usability": "Provides extractable estimates with uncertainty",
            "design_relevance": "Contact tracing study appropriate for SI estimation",
            "parameter_alignment": "Primary aim is to estimate serial interval",
        },
    )

    # Calculate overall score
    overall = scores.calculate_overall_score()
    recommendation = scores.calculate_recommendation()

    print(f"\n📝 Paper Evaluation:")
    print(f"   Overall Score: {overall:.3f}")
    print(f"   Recommendation: {recommendation}")

    print(f"\n✅ HIGH Dimensions:")
    for dim in scores.get_high_dimensions():
        print(f"   - {dim}: {scores.rationales.get(dim, 'N/A')}")

    failed = scores.get_failed_dimensions()
    if failed:
        print(f"\n❌ LOW Dimensions:")
        for dim in failed:
            print(f"   - {dim}")

    print(f"\n📊 Dimension Summary:")
    summary = scores.get_dimension_summary()
    for key, value in summary.items():
        if key not in ["overall_score", "recommendation", "confidence"]:
            print(f"   {key}: {value}")


def example_custom_weights():
    """Example: Calculate score with custom weights."""
    print("\n" + "=" * 80)
    print("Example 4: Custom Dimension Weights")
    print("=" * 80)

    scores = EpiDimensionScores(
        disease_relevance="HIGH",
        original_data="HIGH",
        population_level="LOW",  # Case report
        parameter_availability="MEDIUM",
        statistical_usability="LOW",  # No CI
        design_relevance="MEDIUM",
        parameter_alignment="HIGH",
    )

    # Default weights
    default_score = scores.calculate_overall_score()
    print(f"\n📊 Default Weights:")
    print(f"   Score: {default_score:.3f}")
    print(f"   Recommendation: {scores.calculate_recommendation()}")

    # Custom weights: prioritize data quality over design
    custom_weights = {
        "disease_relevance": 0.25,  # More important
        "original_data": 0.25,  # More important
        "population_level": 0.05,  # Less important
        "parameter_availability": 0.20,  # Important
        "statistical_usability": 0.15,  # Important
        "design_relevance": 0.05,  # Less important
        "parameter_alignment": 0.05,  # Less important
    }

    custom_score = scores.calculate_overall_score(weights=custom_weights)
    print(f"\n📊 Custom Weights (prioritize data quality):")
    print(f"   Score: {custom_score:.3f}")
    print(f"   Recommendation: {scores.calculate_recommendation()}")
    print(f"   Impact: {(custom_score - default_score)*100:+.1f}% vs default")


if __name__ == "__main__":
    print("\n🔬 Multi-Dimensional Literature Screening Examples\n")

    try:
        # Run examples
        example_inspect_dimensions()
        example_manual_scoring()
        example_custom_weights()

        # Uncomment to run full pipeline (requires API keys)
        # example_basic_usage()

        print("\n" + "=" * 80)
        print("✅ All examples completed!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
