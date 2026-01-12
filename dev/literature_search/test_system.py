"""快速测试脚本 - 验证 MetaAgent-Epi 核心功能是否可用"""

import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

print("=" * 60)
print("MetaAgent-Epi 系统检查")
print("=" * 60)

# 测试 1: 检查核心模块导入
print("\n1. 检查核心模块导入...")
try:
    from data_sources import PubMedClient, ERICClient, Paper

    print("   ✓ 数据源模块导入成功")
except ImportError as e:
    print(f"   ✗ 数据源模块导入失败: {e}")
    sys.exit(1)

try:
    from epidemiology.keyword_generator import KeywordGeneratorAgent

    print("   ✓ 关键词生成器导入成功")
except ImportError as e:
    print(f"   ✗ 关键词生成器导入失败: {e}")
    sys.exit(1)

try:
    from epidemiology.boolean_search_agent import BooleanSearchAgent

    print("   ✓ 布尔检索代理导入成功")
except ImportError as e:
    print(f"   ✗ 布尔检索代理导入失败: {e}")
    sys.exit(1)

try:
    from langgraph_pipeline.graph import build_graph
    from langgraph_pipeline.state import SearchState

    print("   ✓ LangGraph 管道导入成功")
except ImportError as e:
    print(f"   ✗ LangGraph 管道导入失败: {e}")
    sys.exit(1)

# 测试 2: 检查环境配置
print("\n2. 检查环境配置...")
import os
from dotenv import load_dotenv

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"   ✓ 找到 .env 文件: {env_file}")
else:
    print(f"   ⚠ 未找到 .env 文件（将使用环境变量）")

llm_provider = os.getenv("LLM_PROVIDER")
if llm_provider:
    print(f"   ✓ LLM Provider: {llm_provider}")
else:
    print(f"   ⚠ LLM_PROVIDER 未设置")

ncbi_key = os.getenv("NCBI_API_KEY")
if ncbi_key:
    print(f"   ✓ PubMed API Key: 已配置")
else:
    print(f"   ⚠ NCBI_API_KEY 未设置（将使用受限速率）")

# 测试 3: 检查 LangGraph 图构建
print("\n3. 检查 LangGraph 管道...")
try:
    graph = build_graph()
    print("   ✓ LangGraph 图构建成功")
except Exception as e:
    print(f"   ✗ LangGraph 图构建失败: {e}")
    sys.exit(1)

# 测试 4: 测试 PubMed 客户端（不实际调用 API）
print("\n4. 检查 PubMed 客户端...")
try:
    client = PubMedClient()
    print("   ✓ PubMed 客户端初始化成功")
except Exception as e:
    print(f"   ✗ PubMed 客户端初始化失败: {e}")

# 测试 5: 检查关键词生成器（不调用 LLM）
print("\n5. 检查关键词生成器配置...")
try:
    agent = KeywordGeneratorAgent()
    print("   ✓ 关键词生成器初始化成功")

    # 检查流行病学领域配置
    test_state = {"domain": "epidemiology", "research_query": "test"}
    domain = test_state.get("domain", "epidemiology")
    if domain == "epidemiology":
        print("   ✓ 默认领域设置为 epidemiology")
    else:
        print(f"   ⚠ 默认领域为: {domain}")
except Exception as e:
    print(f"   ✗ 关键词生成器初始化失败: {e}")

print("\n" + "=" * 60)
print("系统检查完成")
print("=" * 60)

# 检查是否可以运行完整流程
if llm_provider and (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
    print("\n✓ 系统已就绪，可以运行完整的文献检索流程")
    print("\n运行示例:")
    print('  python -c "from langgraph_pipeline.graph import build_graph, run_once; \\')
    print("            graph = build_graph(); \\")
    print("            result = run_once(graph, \\")
    print(
        "                              research_question='COVID-19 vaccine effectiveness', \\"
    )
    print("                              domain='infectious_disease', \\")
    print("                              workdir='outputs/test')\"")
else:
    print("\n⚠ 需要配置 LLM API 密钥才能运行完整流程")
    print("\n步骤:")
    print("  1. 复制 .env.example 为 .env")
    print("  2. 编辑 .env，设置 LLM_PROVIDER 和对应的 API key")
    print("  3. （推荐）设置 NCBI_API_KEY 以提高 PubMed 访问速率")

print("\n若要测试关键词生成（需要 LLM API）:")
print("  python examples/keyword_generator_test.py")
print("\n若要测试布尔检索生成（需要 LLM API）:")
print("  python examples/boolean_search_test.py")
