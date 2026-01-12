"""Example: Keyword generation agent for psychology literature search.

This example demonstrates how to use the keyword generator agent with configuration
from environment variables (.env file).

Environment variables:
    LLM_PROVIDER: Provider name (e.g., "claude", "openai", "siliconflow", or custom)
    LLM_MODEL: Model name (e.g., "claude-3-5-sonnet-20241022", "gpt-4", "Qwen/Qwen2.5-7B-Instruct")
    LLM_TEMPERATURE: Temperature (default: 0.7)
    ANTHROPIC_API_KEY: API key for Claude (if using claude provider)
    OPENAI_API_KEY: API key for OpenAI or SiliconFlow (if using openai/siliconflow provider)
    LLM_API_KEY: Generic API key (fallback for any provider)
    LLM_API_BASE: Custom API base URL (for custom providers, e.g., https://api.siliconflow.cn/v1)
    SILICONFLOW_API_KEY: API key for SiliconFlow (optional, can use OPENAI_API_KEY)
    SILICONFLOW_API_BASE: API base for SiliconFlow (optional, defaults to https://api.siliconflow.cn/v1)

Example .env for SiliconFlow:
    LLM_PROVIDER=siliconflow
    LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
    OPENAI_API_KEY=your_siliconflow_api_key
    OPENAI_API_BASE=https://api.siliconflow.cn/v1
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from epidemiology.keyword_generator import KeywordGeneratorAgent


def main():
    """Example usage of keyword generator agent."""
    print("=" * 60)
    print("Keyword Generator Agent - Example")
    print("=" * 60)

    # Load .env file explicitly from the project directory
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"\nLoaded .env from: {env_path}")
    else:
        # Try alternative locations
        alt_paths = [
            Path(__file__).parent.parent.parent / ".env",
            Path.cwd() / ".env",
        ]
        loaded = False
        for alt_path in alt_paths:
            if alt_path.exists():
                load_dotenv(alt_path, override=True)
                print(f"\nLoaded .env from: {alt_path}")
                loaded = True
                break
        if not loaded:
            print(
                f"\nWarning: No .env file found. Using environment variables or defaults."
            )

    # Show current configuration
    provider = os.getenv("LLM_PROVIDER", "claude")
    model = os.getenv("LLM_MODEL", "default")
    # Support both BASE_URL and API_BASE naming conventions
    api_base = (
        os.getenv("LLM_BASE_URL")
        or os.getenv("LLM_API_BASE")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("SILICONFLOW_BASE_URL")
        or os.getenv("SILICONFLOW_API_BASE")
    )

    print(f"\nConfiguration:")
    print(f"  Provider: {provider}")
    print(f"  Model: {model}")
    print(f"  API Base: {api_base or 'Not set (will use default)'}")

    # Check API keys
    api_keys_found = []
    if os.getenv("ANTHROPIC_API_KEY"):
        api_keys_found.append("ANTHROPIC_API_KEY")
    if os.getenv("OPENAI_API_KEY"):
        api_keys_found.append("OPENAI_API_KEY")
    if os.getenv("LLM_API_KEY"):
        api_keys_found.append("LLM_API_KEY")
    if os.getenv("SILICONFLOW_API_KEY"):
        api_keys_found.append("SILICONFLOW_API_KEY")

    if api_keys_found:
        print(f"  API Key: Set ({', '.join(api_keys_found)})")
    else:
        print(f"  API Key: Not set")

    # 初始化agent - 如果不指定provider，会从环境变量读取
    # 对于 SiliconFlow，可以显式指定: agent = KeywordGeneratorAgent(llm_provider="siliconflow")
    try:
        # If provider is siliconflow but not explicitly set, try to use it
        if provider.lower() in ["siliconflow", "qwen"]:
            print(f"\nDetected SiliconFlow provider, initializing...")
            agent = KeywordGeneratorAgent(llm_provider="siliconflow")
        else:
            agent = KeywordGeneratorAgent()
        print("\nAgent initialized successfully!")
    except ValueError as e:
        print(f"\nError initializing agent: {e}")
        print("\nPlease set the following environment variables in your .env file:")
        print("\nFor SiliconFlow (Qwen):")
        print("  LLM_PROVIDER=siliconflow")
        print("  LLM_MODEL=Qwen/Qwen2.5-7B-Instruct")
        print("  OPENAI_API_KEY=your_siliconflow_api_key")
        print("  OPENAI_BASE_URL=https://api.siliconflow.cn/v1")
        print("  (or use OPENAI_API_BASE, LLM_BASE_URL, or LLM_API_BASE)")
        print("\nFor Claude:")
        print("  LLM_PROVIDER=claude")
        print("  ANTHROPIC_API_KEY=your_claude_key")
        print("\nFor OpenAI:")
        print("  LLM_PROVIDER=openai")
        print("  OPENAI_API_KEY=your_openai_key")
        return

    # 生成关键词 - 使用流行病学示例
    query = "What is the association between air pollution exposure and cardiovascular disease incidence?"
    print(f"\nResearch Query: {query}")
    print("\nGenerating keywords...")

    try:
        keywords = agent.generate(query, domain="environmental_epi")

        # 使用生成的关键词
        print("\n" + "=" * 60)
        print("Generated Keywords:")
        print("=" * 60)
        print(f"\nPrimary Keywords: {keywords.primary_keywords}")
        print(f"\nSynonyms: {keywords.synonyms}")
        print(f"\nRelated Terms: {keywords.related_terms}")
        print(f"\nDomain Terms: {keywords.domain_terms}")
        print(f"\nOutcome Terms: {keywords.outcome_terms}")
        print(f"\nDesign Terms: {keywords.design_terms}")
        print(f"\nSearch Queries:")
        for i, search_query in enumerate(keywords.search_queries, 1):
            print(f"  {i}. {search_query}")

        print("\n" + "=" * 60)
        print("Example complete!")
        print("=" * 60)
    except Exception as e:
        print(f"\nError generating keywords: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
