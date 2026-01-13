#!/usr/bin/env python3
"""
评估文献检索结果与 ground truth 的匹配度

比较检索结果中的 PMID 与 ground truth CSV，计算召回率、精确率等指标
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd


def load_ground_truth(csv_path: Path) -> Set[str]:
    """读取ground truth CSV文件，返回PMID集合"""
    try:
        df = pd.read_csv(csv_path)
        if "PMID" not in df.columns:
            raise ValueError("CSV文件必须包含 'PMID' 列")
        pmids = set(df["PMID"].astype(str).tolist())
        return pmids
    except Exception as e:
        print(f"错误: 无法读取ground truth文件: {e}", file=sys.stderr)
        sys.exit(1)


def load_retrieved_pmids(jsonl_path: Path) -> Set[str]:
    """读取检索结果JSONL文件，返回PMID集合

    注意: raw_pubmed.jsonl已经过normalize_and_dedupe处理，
    是去重后的结果。这里的set操作是为了防御性编程。
    """
    try:
        pmids = set()
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                pmid = obj["id"].replace("pubmed:", "")
                pmids.add(pmid)
        return pmids
    except Exception as e:
        print(f"错误: 无法读取检索结果文件: {e}", file=sys.stderr)
        sys.exit(1)


def calculate_metrics(ground_truth: Set[str], retrieved: Set[str]) -> Dict[str, float]:
    """计算评估指标"""
    matched = ground_truth & retrieved
    missed = ground_truth - retrieved
    extra = retrieved - ground_truth

    recall = (len(matched) / len(ground_truth) * 100) if len(ground_truth) > 0 else 0
    precision = (len(matched) / len(retrieved) * 100) if len(retrieved) > 0 else 0
    f1 = (
        (2 * precision * recall / (precision + recall))
        if (precision + recall) > 0
        else 0
    )

    return {
        "ground_truth_count": len(ground_truth),
        "retrieved_count": len(retrieved),
        "matched_count": len(matched),
        "missed_count": len(missed),
        "extra_count": len(extra),
        "recall": recall,
        "precision": precision,
        "f1_score": f1,
        "matched": matched,
        "missed": missed,
        "extra": extra,
    }


def print_colored(text: str, color: str):
    """打印彩色文本"""
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "reset": "\033[0m",
    }
    print(f"{colors.get(color, '')}{text}{colors['reset']}")


def print_report(
    metrics: Dict,
    run_dir: Path,
    show_details: bool = False,
    ground_truth_df: pd.DataFrame = None,
    jsonl_path: Path = None,
):
    """打印评估报告"""
    print()
    print_colored("=" * 50, "green")
    print_colored("           检索结果评估报告", "green")
    print_colored("=" * 50, "green")
    print(f"\n运行目录: {run_dir}")

    # 基本统计
    print_colored("\n--- 基本统计 ---", "yellow")
    print(f"Ground Truth 文献总数:  {metrics['ground_truth_count']} 篇")
    print(f"检索结果总数 (去重后): {metrics['retrieved_count']} 篇")
    print_colored(f"成功匹配数量:          {metrics['matched_count']} 篇", "cyan")
    print_colored(
        f"遗漏文献数量:          {metrics['missed_count']} 篇 ({metrics['missed_count']/metrics['ground_truth_count']*100:.1f}%)",
        "red",
    )
    print_colored(
        f"额外检索文献数量:      {metrics['extra_count']} 篇 ({metrics['extra_count']/metrics['retrieved_count']*100:.1f}%)",
        "blue",
    )

    # 性能指标
    print_colored("\n--- 性能指标 ---", "yellow")
    recall_color = (
        "green"
        if metrics["recall"] >= 80
        else "yellow" if metrics["recall"] >= 60 else "red"
    )
    precision_color = (
        "green"
        if metrics["precision"] >= 80
        else "yellow" if metrics["precision"] >= 60 else "red"
    )
    f1_color = (
        "green"
        if metrics["f1_score"] >= 80
        else "yellow" if metrics["f1_score"] >= 60 else "red"
    )

    print_colored(f"召回率 (Recall):       {metrics['recall']:.2f}%", recall_color)
    print_colored(
        f"精确率 (Precision):    {metrics['precision']:.2f}%", precision_color
    )
    print_colored(f"F1 分数:               {metrics['f1_score']:.2f}%", f1_color)

    # 详细信息
    if show_details:
        # 遗漏的文献
        if metrics["missed_count"] > 0 and ground_truth_df is not None:
            print_colored("\n--- 遗漏的文献 (前 15 篇) ---", "red")
            missed_pmids = list(metrics["missed"])[:15]
            missed_df = ground_truth_df[
                ground_truth_df["PMID"].astype(str).isin(missed_pmids)
            ]
            missed_df = missed_df[["PMID", "Title", "Publication Year"]].head(15)
            print(missed_df.to_string(index=False))

        # 额外的文献
        if metrics["extra_count"] > 0 and jsonl_path is not None:
            print_colored("\n--- 额外检索到的文献 (前 15 篇) ---", "blue")
            extra_pmids = list(metrics["extra"])[:15]
            extra_records = []
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line)
                    pmid = obj["id"].replace("pubmed:", "")
                    if pmid in extra_pmids:
                        title = obj["title"]
                        if len(title) > 80:
                            title = title[:80] + "..."
                        year = obj["published"][:4] if obj.get("published") else "N/A"
                        extra_records.append(
                            {"PMID": pmid, "Title": title, "Year": year}
                        )
                        if len(extra_records) >= 15:
                            break

            if extra_records:
                extra_df = pd.DataFrame(extra_records)
                print(extra_df.to_string(index=False))

        # 成功匹配的文献示例
        if metrics["matched_count"] > 0 and ground_truth_df is not None:
            print_colored("\n--- 成功匹配的文献 (随机 10 篇) ---", "green")
            matched_pmids = list(metrics["matched"])[:10]
            matched_df = ground_truth_df[
                ground_truth_df["PMID"].astype(str).isin(matched_pmids)
            ]
            matched_df = matched_df[["PMID", "Title", "Publication Year"]].head(10)
            print(matched_df.to_string(index=False))

    print_colored("\n" + "=" * 50, "green")
    if not show_details:
        print("提示: 使用 --details 参数查看详细文献列表")
    print_colored("=" * 50 + "\n", "green")


def main():
    parser = argparse.ArgumentParser(
        description="评估文献检索结果与 ground truth 的匹配度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/evaluate_retrieval.py langgraph_runs/run_20260113_001117
  python scripts/evaluate_retrieval.py langgraph_runs/run_20260113_001117 --details
  python scripts/evaluate_retrieval.py langgraph_runs/run_20260113_001117 --ground-truth custom_gt.csv
        """,
    )

    parser.add_argument(
        "run_dir",
        type=str,
        help="检索运行目录路径，例如: langgraph_runs/run_20260113_001117",
    )

    parser.add_argument(
        "--ground-truth",
        type=str,
        default="langgraph_runs/ground_truth/searchA.csv",
        help="Ground truth CSV 文件路径 (默认: langgraph_runs/ground_truth/searchA.csv)",
    )

    parser.add_argument(
        "--details", action="store_true", help="显示详细的遗漏和额外文献列表"
    )

    parser.add_argument("--output", type=str, help="将结果保存到JSON文件")

    args = parser.parse_args()

    # 验证路径
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"错误: 运行目录不存在: {run_dir}", file=sys.stderr)
        sys.exit(1)

    ground_truth_path = Path(args.ground_truth)
    if not ground_truth_path.exists():
        print(f"错误: Ground truth 文件不存在: {ground_truth_path}", file=sys.stderr)
        sys.exit(1)

    retrieved_path = run_dir / "cache" / "raw_pubmed.jsonl"
    if not retrieved_path.exists():
        print(f"错误: 检索结果文件不存在: {retrieved_path}", file=sys.stderr)
        sys.exit(1)

    # 加载数据
    print_colored("\n正在加载 ground truth...", "cyan")
    ground_truth_pmids = load_ground_truth(ground_truth_path)
    ground_truth_df = pd.read_csv(ground_truth_path) if args.details else None

    print_colored("正在加载检索结果...", "cyan")
    retrieved_pmids = load_retrieved_pmids(retrieved_path)

    # 计算指标
    metrics = calculate_metrics(ground_truth_pmids, retrieved_pmids)

    # 打印报告
    print_report(
        metrics,
        run_dir,
        args.details,
        ground_truth_df=ground_truth_df,
        jsonl_path=retrieved_path if args.details else None,
    )

    # 保存到JSON
    if args.output:
        output_data = {
            "run_dir": str(run_dir),
            "ground_truth_file": str(ground_truth_path),
            "metrics": {
                "ground_truth_count": metrics["ground_truth_count"],
                "retrieved_count": metrics["retrieved_count"],
                "matched_count": metrics["matched_count"],
                "missed_count": metrics["missed_count"],
                "extra_count": metrics["extra_count"],
                "recall": round(metrics["recall"], 2),
                "precision": round(metrics["precision"], 2),
                "f1_score": round(metrics["f1_score"], 2),
            },
            "matched_pmids": list(metrics["matched"]),
            "missed_pmids": list(metrics["missed"]),
            "extra_pmids": list(metrics["extra"]),
        }

        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
