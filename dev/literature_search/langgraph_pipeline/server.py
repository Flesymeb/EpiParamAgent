import sys
from pathlib import Path

# Ensure project src is on sys.path for imports like `data_sources`
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TOOLS = ROOT.parent / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from common.config import apply_langsmith_env, load_runtime_env

load_runtime_env(module_hint="literature_search")
apply_langsmith_env(module_hint="literature_search")

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
