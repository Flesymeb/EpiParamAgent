#!/usr/bin/env python3
"""
将CSV文献数据转换为RIS格式（用于EndNote、Mendeley等文献管理软件）

使用方法:
    python convert_csv_to_ris.py --input ../langgraph_runs/ground_truth/search_v2/search_v2_raw.csv --output search_v2.ris
"""

import argparse
import csv
import sys
from pathlib import Path


def clean_field(text: str) -> str:
    """清理字段内容，移除换行符和多余空格"""
    if not text:
        return ""
    return " ".join(text.replace("\n", " ").split())


def parse_authors(authors_str: str) -> list:
    """解析作者字符串，返回作者列表"""
    if not authors_str or authors_str.strip() == "":
        return []

    # 移除尾部的句号
    authors_str = authors_str.rstrip(".")

    # 按逗号分隔作者（假设格式为: Last1 FM1, Last2 FM2, Last3 FM3）
    authors = []
    parts = authors_str.split(",")

    for part in parts:
        part = part.strip()
        if part:
            authors.append(part)

    return authors


def csv_to_ris(input_file: Path, output_file: Path):
    """将CSV文件转换为RIS格式"""

    if not input_file.exists():
        print(f"❌ 错误: 输入文件不存在: {input_file}")
        sys.exit(1)

    ris_entries = []
    total_records = 0

    with open(input_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            total_records += 1

            # 开始一条RIS记录
            ris_lines = []

            # TY - Type of reference (JOUR = Journal Article)
            ris_lines.append("TY  - JOUR")

            # TI - Title
            title = clean_field(row.get("Title", ""))
            if title:
                ris_lines.append(f"TI  - {title}")

            # AU - Authors (每个作者一行)
            authors_str = row.get("Authors", "")
            authors = parse_authors(authors_str)
            for author in authors:
                ris_lines.append(f"AU  - {author}")

            # PY - Publication Year
            year = row.get("Publication Year", "")
            if year:
                ris_lines.append(f"PY  - {year}")

            # JO - Journal/Book
            journal = clean_field(row.get("Journal/Book", ""))
            if journal:
                ris_lines.append(f"JO  - {journal}")

            # AB - Abstract
            abstract = clean_field(row.get("Abstract", ""))
            if abstract and abstract != "No abstract available":
                ris_lines.append(f"AB  - {abstract}")

            # DO - DOI
            doi = row.get("DOI", "")
            if doi:
                ris_lines.append(f"DO  - {doi}")

            # UR - URL (构建PubMed链接)
            pmid = row.get("PMID", "")
            if pmid:
                ris_lines.append(f"UR  - https://pubmed.ncbi.nlm.nih.gov/{pmid}/")

            # AN - Accession Number (PMID)
            if pmid:
                ris_lines.append(f"AN  - {pmid}")

            # DB - Database
            ris_lines.append("DB  - PubMed")

            # ER - End of Reference
            ris_lines.append("ER  - ")
            ris_lines.append("")  # 空行分隔不同记录

            ris_entries.append("\n".join(ris_lines))

    # 写入RIS文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(ris_entries))

    print(f"✅ 转换完成!")
    print(f"   输入: {input_file}")
    print(f"   输出: {output_file}")
    print(f"   共转换 {total_records} 条文献记录")
    print(f"\n💡 可导入至: EndNote, Mendeley, Zotero, RefWorks 等文献管理软件")


def main():
    parser = argparse.ArgumentParser(description="将CSV文献数据转换为RIS格式")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="输入CSV文件路径",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="输出RIS文件路径",
    )

    args = parser.parse_args()

    csv_to_ris(args.input, args.output)


if __name__ == "__main__":
    main()
