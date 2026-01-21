"""
筛选结果评估工具 - 统一评估检索和筛选效果

功能：
1. 评估搜索策略覆盖率（search coverage）
2. 评估LLM筛选效果（screening performance with confusion matrix）
3. 评估检索结果的召回率和精确率

使用示例：
    # 评估搜索覆盖率
    python screening_evaluation.py search-coverage --ground-truth ../langgraph_runs/ground_truth/search_v2/search_v2_gt.csv --search-results ../langgraph_runs/ground_truth/search_v2/search_v2_raw.csv

    # 评估筛选效果（含混淆矩阵）
    python screening_evaluation.py screening-performance --ground-truth ../langgraph_runs/ground_truth/search_v2/search_v2_gt.csv --screened-results ../langgraph_runs/ground_truth/search_v2/test_screen/search_v2_screened.csv

    # 评估检索召回率
    python screening_evaluation.py retrieval-metrics --ground-truth outputs/raw.csv --retrieved-results langgraph_runs/results/raw_pubmed.jsonl
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Set CSV field size limit to maximum possible value
try:
    csv.field_size_limit(sys.maxsize)
except (AttributeError, ValueError, OverflowError):
    try:
        csv.field_size_limit(2**31 - 1)  # 2GB fallback
    except (AttributeError, ValueError, OverflowError):
        pass


def load_ground_truth_pmids(csv_file: Path) -> Dict[str, Dict]:
    """
    从ground truth CSV加载PMIDs

    Returns:
        Dict[pmid -> {id, title, first_author, year, variant_focus}]
    """
    ground_truth = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 处理可能的BOM
            pmid = None
            for key in ["PMID", "\ufeffPMID"]:
                if key in row:
                    pmid_val = row[key].strip()
                    if pmid_val and pmid_val.isdigit():
                        pmid = pmid_val
                        break

            if pmid:
                ground_truth[pmid] = {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "first_author": row.get("first_author", ""),
                    "year": row.get("year", ""),
                    "variant_focus": row.get("variant_focus", ""),
                }

    return ground_truth


def load_search_results(csv_file: Path) -> Set[str]:
    """加载搜索结果的PMID集合"""
    pmids = set()
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = row.get("PMID", "").strip()
            if pmid:
                pmids.add(pmid)
    return pmids


def load_screened_results(csv_file: Path) -> Dict[str, Dict]:
    """
    加载筛选结果

    Returns:
        Dict[pmid -> {llm_suggest, overall_score, dimension scores, ...}]
    """
    screened = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = row.get("PMID", "").strip()
            if pmid:
                screened[pmid] = {
                    "llm_suggest": row.get("llm_suggest", ""),
                    "overall_score": row.get("overall_score", "0"),
                    "overall_justification": row.get("overall_justification", ""),
                    "title": row.get("Title", ""),
                    # 5个核心维度评分
                    "disease_score": int(row.get("disease_score", "0") or "0"),
                    "population_score": int(row.get("population_score", "0") or "0"),
                    "location_score": int(row.get("location_score", "0") or "0"),
                    "evidence_score": int(row.get("evidence_score", "0") or "0"),
                    "transmission_score": int(
                        row.get("transmission_score", "0") or "0"
                    ),
                }
    return screened


def load_retrieved_jsonl(jsonl_file: Path) -> Set[str]:
    """从JSONL文件加载检索到的PMIDs"""
    pmids = set()
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            pmid = obj["id"].replace("pubmed:", "")
            pmids.add(pmid)
    return pmids


def evaluate_search_coverage(
    ground_truth: Dict[str, Dict], search_results: Set[str]
) -> None:
    """评估搜索策略对ground truth的覆盖率"""
    print("\n" + "=" * 100)
    print("📊 搜索覆盖率分析")
    print("=" * 100)

    total_gt = len(ground_truth)
    found = set(ground_truth.keys()) & search_results
    not_found = set(ground_truth.keys()) - search_results

    coverage = len(found) / total_gt * 100 if total_gt > 0 else 0

    print(f"\nGround Truth总数: {total_gt} 篇")
    print(f"搜索结果总数: {len(search_results)} 篇")
    print(f"\n✅ 在搜索结果中找到: {len(found)} 篇 ({coverage:.1f}%)")
    print(
        f"❌ 未在搜索结果中找到: {len(not_found)} 篇 ({len(not_found)/total_gt*100:.1f}%)"
    )

    if not_found:
        print(f"\n\n❌ 未被搜索到的Ground Truth论文:\n")
        print("=" * 100)
        for i, pmid in enumerate(sorted(not_found), 1):
            gt = ground_truth[pmid]
            print(f"[{i}] PMID: {pmid} | {gt['first_author']} ({gt['year']})")
            print(f"    变异株: {gt['variant_focus']}")
            print(f"    标题: {gt['title']}")
            print()


def meets_core_criteria(paper: Dict, threshold: int = 3) -> bool:
    """
    判断论文是否满足所有核心纳入标准

    Args:
        paper: 论文数据（包含5个维度评分）
        threshold: 每个维度的最低分数要求（默认3分=比较相关）

    Returns:
        True if 所有5个维度都 >= threshold
    """
    dimensions = [
        "disease_score",
        "population_score",
        "location_score",
        "evidence_score",
        "transmission_score",
    ]
    return all(paper.get(dim, 0) >= threshold for dim in dimensions)


def evaluate_screening_performance(
    ground_truth: Dict[str, Dict], screened: Dict[str, Dict]
) -> None:
    """评估LLM筛选效果（含混淆矩阵）"""
    print("\n" + "=" * 100)
    print("📊 LLM筛选效果分析（含混淆矩阵）")
    print("=" * 100)

    # 分类ground truth
    strong = []
    possible = []
    unlikely = []
    not_found = []

    for pmid, gt in ground_truth.items():
        if pmid in screened:
            suggest = screened[pmid]["llm_suggest"]
            if suggest == "strong_candidate":
                strong.append(pmid)
            elif suggest == "possible_candidate":
                possible.append(pmid)
            else:
                unlikely.append(pmid)
        else:
            not_found.append(pmid)

    total_gt = len(ground_truth)
    combined_relevant = len(strong) + len(possible)

    print(
        f"\n📋 Ground Truth 分类统计 (总数: {total_gt} 篇 | 筛选池: {len(screened)} 篇)\n"
    )
    print(f"┌─────────────────────────────┬─────────┬─────────┐")
    print(f"│ 类别                        │  数量   │  占比   │")
    print(f"├─────────────────────────────┼─────────┼─────────┤")
    print(
        f"│ 💪 Strong candidates        │  {len(strong):4d}   │ {len(strong)/total_gt*100:5.1f}%  │"
    )
    print(
        f"│ 🤔 Possible candidates      │  {len(possible):4d}   │ {len(possible)/total_gt*100:5.1f}%  │"
    )
    print(
        f"│ 😐 Unlikely candidates      │  {len(unlikely):4d}   │ {len(unlikely)/total_gt*100:5.1f}%  │"
    )
    print(
        f"│ ❌ 未找到                   │  {len(not_found):4d}   │ {len(not_found)/total_gt*100:5.1f}%  │"
    )
    print(f"├─────────────────────────────┼─────────┼─────────┤")
    print(
        f"│ 🎯 综合召回 (S+P)           │  {combined_relevant:4d}   │ {combined_relevant/total_gt*100:5.1f}%  │"
    )
    print(
        f"│ 💎 高质量召回 (S only)      │  {len(strong):4d}   │ {len(strong)/total_gt*100:5.1f}%  │"
    )
    print(f"└─────────────────────────────┴─────────┴─────────┘")

    # 混淆矩阵
    print(f"\n\n" + "=" * 100)
    print(f"\n📋 混淆矩阵分析（三分类）\n")

    # 非ground truth的分类
    non_gt_pmids = set(screened.keys()) - set(ground_truth.keys())
    FP_strong = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "strong_candidate"
    )
    FP_possible = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "possible_candidate"
    )
    TN = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "unlikely_candidate"
    )

    print("混淆矩阵:")
    print(f"┌─────────────────────────┬──────────────────┬──────────────────┐")
    print(f"│                         │   实际相关(GT)   │   实际不相关     │")
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 💪 Strong               │      {len(strong):2d}          │      {FP_strong:2d}          │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 🤔 Possible             │      {len(possible):2d}          │      {FP_possible:2d}          │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 😐 Unlikely             │      {len(unlikely)+len(not_found):2d}          │      {TN:2d}          │"
    )
    print(f"└─────────────────────────┴──────────────────┴──────────────────┘")

    # 合并后的二分类混淆矩阵
    print(f"\n\n📋 混淆矩阵（合并S+P为相关）\n")
    TP = combined_relevant  # Ground truth被正确识别为相关
    FN = len(unlikely) + len(not_found)  # Ground truth被错误标记为不相关
    FP = FP_strong + FP_possible  # 非GT被错误标记为相关

    print(f"┌─────────────────────────┬──────────────────┬──────────────────┐")
    print(f"│                         │   实际相关(GT)   │   实际不相关     │")
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 预测相关(S+P)           │   TP = {TP:2d}        │   FP = {FP:2d}        │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 预测不相关(Unlikely)    │   FN = {FN:2d}        │   TN = {TN:2d}        │"
    )
    print(f"└─────────────────────────┴──────────────────┴──────────────────┘")

    # 性能指标
    sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0
    specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0
    npv = TN / (TN + FN) if (TN + FN) > 0 else 0
    f1 = (
        2 * (precision * sensitivity) / (precision + sensitivity)
        if (precision + sensitivity) > 0
        else 0
    )
    accuracy = (TP + TN) / (TP + TN + FP + FN) if (TP + TN + FP + FN) > 0 else 0

    print(f"\n📊 性能指标:")
    print(f"┌─────────────────────────────┬─────────┬─────────────────────────┐")
    print(f"│ 指标                        │  数值   │  计算公式               │")
    print(f"├─────────────────────────────┼─────────┼─────────────────────────┤")
    print(
        f"│ 📈 Sensitivity (召回率)     │ {sensitivity:6.1%}  │ TP/(TP+FN) = {TP}/{TP+FN:2d}      │"
    )
    print(
        f"│ 🎯 Specificity (特异度)     │ {specificity:6.1%}  │ TN/(TN+FP) = {TN}/{TN+FP:2d}      │"
    )
    print(
        f"│ 💎 Precision (精确率)       │ {precision:6.1%}  │ TP/(TP+FP) = {TP}/{TP+FP:2d}      │"
    )
    print(
        f"│ ✅ NPV (阴性预测值)         │ {npv:6.1%}  │ TN/(TN+FN) = {TN}/{TN+FN:2d}      │"
    )
    print(f"│ 🏆 F1-score                 │ {f1:6.1%}  │ 2×P×R/(P+R)             │")
    print(
        f"│ ✨ Accuracy (准确率)        │ {accuracy:6.1%}  │ (TP+TN)/Total = {TP+TN}/{TP+TN+FP+FN}   │"
    )
    print(f"└─────────────────────────────┴─────────┴─────────────────────────┘")


def evaluate_retrieval_metrics(
    ground_truth_pmids: Set[str], retrieved_pmids: Set[str]
) -> None:
    """评估检索结果的召回率和精确率"""
    print("\n" + "=" * 100)
    print("📊 检索指标分析")
    print("=" * 100)

    tp = len(ground_truth_pmids & retrieved_pmids)
    fp = len(retrieved_pmids - ground_truth_pmids)
    fn = len(ground_truth_pmids - retrieved_pmids)

    recall = tp / len(ground_truth_pmids) if len(ground_truth_pmids) > 0 else 0
    precision = tp / len(retrieved_pmids) if len(retrieved_pmids) > 0 else 0
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0
    )

    print(f"\nGround Truth: {len(ground_truth_pmids)} 篇")
    print(f"检索结果: {len(retrieved_pmids)} 篇")
    print(f"\nTP (命中): {tp}")
    print(f"FP (误检): {fp}")
    print(f"FN (漏检): {fn}")
    print(f"\n📈 Recall (召回率): {recall:.1%}")
    print(f"💎 Precision (精确率): {precision:.1%}")
    print(f"🏆 F1-score: {f1:.1%}")


def main():
    parser = argparse.ArgumentParser(
        description="筛选结果评估工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # search-coverage
    search_parser = subparsers.add_parser("search-coverage", help="评估搜索覆盖率")
    search_parser.add_argument(
        "--ground-truth", required=True, help="Ground truth CSV文件"
    )
    search_parser.add_argument(
        "--search-results", required=True, help="搜索结果CSV文件"
    )

    # screening-performance
    screen_parser = subparsers.add_parser("screening-performance", help="评估筛选效果")
    screen_parser.add_argument(
        "--ground-truth", required=True, help="Ground truth CSV文件"
    )
    screen_parser.add_argument(
        "--screened-results", required=True, help="筛选结果CSV文件"
    )

    # retrieval-metrics
    retrieval_parser = subparsers.add_parser("retrieval-metrics", help="评估检索指标")
    retrieval_parser.add_argument(
        "--ground-truth", required=True, help="Ground truth CSV文件"
    )
    retrieval_parser.add_argument(
        "--retrieved-results", required=True, help="检索结果JSONL文件"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "search-coverage":
        gt_file = Path(args.ground_truth)
        search_file = Path(args.search_results)

        ground_truth = load_ground_truth_pmids(gt_file)
        search_results = load_search_results(search_file)

        evaluate_search_coverage(ground_truth, search_results)

    elif args.command == "screening-performance":
        gt_file = Path(args.ground_truth)
        screened_file = Path(args.screened_results)

        ground_truth = load_ground_truth_pmids(gt_file)
        screened = load_screened_results(screened_file)

        evaluate_screening_performance(ground_truth, screened)

    elif args.command == "retrieval-metrics":
        gt_file = Path(args.ground_truth)
        retrieved_file = Path(args.retrieved_results)

        ground_truth = load_ground_truth_pmids(gt_file)
        retrieved = load_retrieved_jsonl(retrieved_file)

        evaluate_retrieval_metrics(set(ground_truth.keys()), retrieved)


if __name__ == "__main__":
    main()
