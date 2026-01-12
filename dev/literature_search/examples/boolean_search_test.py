from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from epidemiology.keyword_generator import KeywordGeneratorAgent
from epidemiology.boolean_search_agent import BooleanSearchAgent


def main():
    agent = KeywordGeneratorAgent(llm_provider="siliconflow")
    kws = agent.generate(
        "What is the association between COVID-19 vaccination and myocarditis risk?",
        domain="infectious_disease",
    )

    b = BooleanSearchAgent(provider="generic", max_queries=15)
    queries = b.generate_queries(kws)

    print("Generated boolean queries for PubMed/generic database:\n")
    for i, q in enumerate(queries, 1):
        print(f"{i}. {q}")


if __name__ == "__main__":
    main()
