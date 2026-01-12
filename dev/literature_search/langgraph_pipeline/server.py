import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path, override=False)

# LangSmith variable shims
import os

if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

# Ensure project src is on sys.path for imports like `data_sources`
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from langgraph_pipeline.graph import build_graph

graph = build_graph()


# from langgraph_pipeline.graph import build_graph, run_once

# g = build_graph()
# state = run_once(
#     g,
#     research_question="theory of mind in preschool children",
#     workdir="langgraph_runs/example1",
#     params={"pubmed_retmax": 3, "eric_limit": 3, "min_year": 2000},
# )
# print("raw:", {k: len(v) for k, v in state.raw_records.items()})
# print("deduped:", len(state.deduped_records))
# print("included:", len(state.included))
