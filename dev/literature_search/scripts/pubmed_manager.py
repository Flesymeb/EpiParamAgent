"""
PubMed数据管理工具 - 统一处理PubMed数据的获取和更新

功能：
1. 根据PMID列表补充论文元数据到CSV
2. 为现有CSV补全abstract字段
3. 批量获取论文详细信息

使用示例：
    # 补充遗漏的论文
    python pubmed_manager.py append --pmids 12345,67890 --output search.csv

    # 补全abstract
    python pubmed_manager.py enrich-abstracts --input search.csv --output search_with_abstracts.csv

    # 批量获取论文信息
    python pubmed_manager.py fetch --pmids 12345,67890 --output papers.csv
"""

import os
import sys
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_sources.pubmed_client import PubMedClient


def fetch_paper_details(pmids: List[str], client: PubMedClient) -> List[Dict]:
    """
    使用PubMed API获取论文详细信息

    Returns:
        List of dicts with keys: PMID, Title, Authors, Citation, First Author,
        Journal/Book, Publication Year, Create Date, PMCID, NIHMS ID, DOI, Abstract
    """
    if not pmids:
        return []

    papers = client._fetch_details(pmids)

    results = []
    for paper in papers:
        pmid = paper.id.replace("pubmed:", "")

        # 提取第一作者
        first_author = ""
        if paper.authors:
            first_author = paper.authors[0].split()[0]

        # 构建citation
        citation_parts = []
        if paper.journal_ref:
            citation_parts.append(paper.journal_ref)
        if paper.published:
            year = paper.published.year
            citation_parts.append(f"{year}")
        if paper.doi:
            citation_parts.append(f"doi: {paper.doi}.")
        citation = ". ".join(citation_parts) + "." if citation_parts else ""

        # 提取创建日期
        create_date = ""
        if paper.published:
            create_date = paper.published.strftime("%Y/%m/%d")

        results.append(
            {
                "PMID": pmid,
                "Title": paper.title,
                "Authors": ", ".join(paper.authors) if paper.authors else "",
                "Citation": citation,
                "First Author": first_author,
                "Journal/Book": paper.journal_ref or "",
                "Publication Year": paper.published.year if paper.published else "",
                "Create Date": create_date,
                "PMCID": "",  # PubMedClient不直接返回PMCID
                "NIHMS ID": "",
                "DOI": paper.doi or "",
                "Abstract": paper.abstract,
            }
        )

    return results


def append_papers_to_csv(pmids: List[str], csv_file: Path, client: PubMedClient):
    """将新论文追加到CSV文件"""
    # 读取现有PMIDs
    existing_pmids = set()
    if csv_file.exists():
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pmid = row.get("PMID", "").strip()
                if pmid:
                    existing_pmids.add(pmid)

    # 过滤已存在的PMIDs
    new_pmids = [p for p in pmids if p not in existing_pmids]

    if not new_pmids:
        print(f"✅ 所有PMID已存在于 {csv_file.name}")
        return

    print(f"📥 获取 {len(new_pmids)} 篇新论文...")
    new_papers = fetch_paper_details(new_pmids, client)

    if not new_papers:
        print("❌ 未获取到任何论文数据")
        return

    # 追加到CSV
    with open(csv_file, "a", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(new_papers[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        # 如果文件为空，写入表头
        if csv_file.stat().st_size == 0:
            writer.writeheader()

        for paper in new_papers:
            writer.writerow(paper)
            print(f"  ✅ {paper['PMID']}: {paper['Title'][:60]}...")

    print(f"🎉 成功追加 {len(new_papers)} 篇论文到 {csv_file.name}")


def enrich_with_abstracts(input_csv: Path, output_csv: Path, client: PubMedClient):
    """为CSV文件补全abstract字段"""
    print(f"📖 读取 {input_csv.name}...")
    papers = []
    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        papers = list(reader)

    print(f"   总计: {len(papers)} 篇论文")

    # 找出缺少abstract的论文
    missing_abstract = []
    for paper in papers:
        pmid = paper.get("PMID", "").strip()
        abstract = paper.get("Abstract", "").strip()
        if pmid and not abstract:
            missing_abstract.append(pmid)

    if not missing_abstract:
        print("✅ 所有论文都已有abstract!")
        if input_csv != output_csv:
            import shutil

            shutil.copy(input_csv, output_csv)
        return

    print(f"📥 需要补全abstract: {len(missing_abstract)} 篇")

    # 获取abstracts
    fetched_papers = fetch_paper_details(missing_abstract, client)
    pmid_to_abstract = {p["PMID"]: p["Abstract"] for p in fetched_papers}

    # 更新papers
    for paper in papers:
        pmid = paper.get("PMID", "").strip()
        if pmid in pmid_to_abstract:
            paper["Abstract"] = pmid_to_abstract[pmid]
            print(f"  ✅ {pmid}: abstract长度 {len(pmid_to_abstract[pmid])} 字符")

    # 写入输出文件
    if papers:
        fieldnames = list(papers[0].keys())
        if "Abstract" not in fieldnames:
            fieldnames.append("Abstract")

        with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(papers)

    print(f"🎉 已保存到 {output_csv.name}")


def batch_fetch(pmids: List[str], output_csv: Path, client: PubMedClient):
    """批量获取论文并保存到新CSV"""
    print(f"📥 获取 {len(pmids)} 篇论文...")
    papers = fetch_paper_details(pmids, client)

    if not papers:
        print("❌ 未获取到任何论文数据")
        return

    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(papers[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    print(f"🎉 成功保存 {len(papers)} 篇论文到 {output_csv.name}")


def main():
    parser = argparse.ArgumentParser(
        description="PubMed数据管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # append命令
    append_parser = subparsers.add_parser("append", help="追加论文到CSV")
    append_parser.add_argument("--pmids", required=True, help="PMID列表（逗号分隔）")
    append_parser.add_argument("--output", required=True, help="输出CSV文件")

    # enrich-abstracts命令
    enrich_parser = subparsers.add_parser("enrich-abstracts", help="补全abstract字段")
    enrich_parser.add_argument("--input", required=True, help="输入CSV文件")
    enrich_parser.add_argument("--output", required=True, help="输出CSV文件")

    # fetch命令
    fetch_parser = subparsers.add_parser("fetch", help="批量获取论文")
    fetch_parser.add_argument("--pmids", required=True, help="PMID列表（逗号分隔）")
    fetch_parser.add_argument("--output", required=True, help="输出CSV文件")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 初始化PubMed客户端
    client = PubMedClient()

    if args.command == "append":
        pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
        output_file = Path(args.output)
        append_papers_to_csv(pmids, output_file, client)

    elif args.command == "enrich-abstracts":
        input_file = Path(args.input)
        output_file = Path(args.output)
        enrich_with_abstracts(input_file, output_file, client)

    elif args.command == "fetch":
        pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
        output_file = Path(args.output)
        batch_fetch(pmids, output_file, client)


if __name__ == "__main__":
    main()
