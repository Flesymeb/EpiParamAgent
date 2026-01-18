#!/usr/bin/env python3
"""
根据PMID列表逐个获取详细信息（修复版）
"""

import csv
import time
import requests
from pathlib import Path
import xml.etree.ElementTree as ET


def fetch_pubmed_details(pmid: str) -> dict:
    """
    通过EFetch API获取单个PMID的详细信息
    """
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}

    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            return {}

        root = ET.fromstring(response.content)
        article = root.find(".//PubmedArticle")
        if not article:
            return {}

        # 提取信息
        medline = article.find(".//MedlineCitation")
        article_elem = medline.find(".//Article")

        # 标题
        title_elem = article_elem.find(".//ArticleTitle")
        title = "".join(title_elem.itertext()) if title_elem is not None else ""

        # 摘要 - 获取所有AbstractText元素（可能有多个部分如Background, Methods等）
        abstract_parts = []
        abstract_node = article_elem.find(".//Abstract")
        if abstract_node is not None:
            for abstract_text in abstract_node.findall(".//AbstractText"):
                # 获取Label属性（如Background, Methods等）
                label = abstract_text.get("Label", "")
                text = "".join(abstract_text.itertext()).strip()
                if text:
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        # 作者
        authors = []
        for author in article_elem.findall(".//Author"):
            last = author.findtext("LastName", "")
            init = author.findtext("Initials", "")
            if last:
                authors.append(f"{last} {init}".strip())

        first_author = authors[0].split()[0] if authors else ""

        # 期刊和年份
        journal = article_elem.findtext(".//Journal/Title", "")
        pub_date = article_elem.find(".//Journal/JournalIssue/PubDate")
        year = ""
        if pub_date is not None:
            year = pub_date.findtext("Year", "")
            if not year:
                year = (
                    pub_date.findtext("MedlineDate", "")[:4]
                    if pub_date.findtext("MedlineDate")
                    else ""
                )

        # DOI
        doi = ""
        for id_elem in article_elem.findall(".//ELocationID"):
            if id_elem.get("EIdType") == "doi":
                doi = id_elem.text
                break

        # Keywords - 包括作者提供的keywords和MeSH terms
        keywords = []

        # 1. 作者提供的Keywords
        keyword_list = medline.find(".//KeywordList")
        if keyword_list is not None:
            for kw in keyword_list.findall(".//Keyword"):
                if kw.text:
                    keywords.append(kw.text.strip())

        # 2. MeSH terms（医学主题词）
        mesh_list = medline.find(".//MeshHeadingList")
        if mesh_list is not None:
            for mesh in mesh_list.findall(".//MeshHeading"):
                descriptor = mesh.find(".//DescriptorName")
                if descriptor is not None and descriptor.text:
                    # MeSH terms通常更权威，标记为MeSH
                    keywords.append(f"[MeSH] {descriptor.text.strip()}")

        keywords_str = "; ".join(keywords) if keywords else ""

        return {
            "title": title,
            "abstract": abstract,
            "first_author": first_author,
            "authors": ", ".join(authors),
            "year": year,
            "journal": journal,
            "doi": doi,
            "keywords": keywords_str,
        }

    except Exception as e:
        print(f"      错误: {str(e)[:50]}")
        return {}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="根据PMID获取缺失的文献详细信息")
    parser.add_argument("--input", type=str, required=True, help="输入CSV文件路径")
    parser.add_argument("--output", type=str, required=True, help="输出CSV文件路径")
    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output)

    print(f"读取: {input_file}\n")

    with open(input_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"总数: {len(rows)} 篇\n")

    # 确保原始数据中有keywords列
    if rows and "Keywords" not in rows[0]:
        for row in rows:
            row["Keywords"] = ""

    # 逐个获取详细信息（仅处理摘要为空的记录）
    updated = 0
    skipped = 0
    for i, row in enumerate(rows, 1):
        pmid = row.get("PMID", "").strip()
        if not pmid:
            print(f"[{i:2d}] 无PMID，跳过")
            continue

        # 检查摘要和keywords是否都已存在
        abstract = row.get("Abstract", "").strip()
        keywords = row.get("Keywords", "").strip()

        if abstract and keywords:
            print(f"[{i:2d}] PMID {pmid} ✓ 已有摘要和Keywords，跳过")
            skipped += 1
            continue

        # 标记需要更新的内容
        need_abstract = not abstract
        need_keywords = not keywords
        update_msg = []
        if need_abstract:
            update_msg.append("摘要")
        if need_keywords:
            update_msg.append("Keywords")

        print(
            f"[{i:2d}] PMID {pmid} [缺少: {', '.join(update_msg)}] ", end="", flush=True
        )

        details = fetch_pubmed_details(pmid)

        if details:
            # 更新基本信息
            row["Title"] = details["title"]
            row["First Author"] = details["first_author"]
            row["Publication Year"] = details["year"]
            row["Journal/Book"] = details["journal"]
            row["DOI"] = details["doi"]

            # 只更新缺失的字段
            if need_abstract:
                row["Abstract"] = details["abstract"]
            if need_keywords:
                row["Keywords"] = details.get("keywords", "")

            print(f"✓ {details['first_author']} ({details['year']})")
            updated += 1
        else:
            print(f"✗ 获取失败")

        time.sleep(0.35)

    # 保存前清理换行符（避免CSV格式问题）
    for row in rows:
        # 清理所有字段中的换行符，用空格替换
        for key in row.keys():
            if isinstance(row[key], str):
                row[key] = row[key].replace("\n", " ").replace("\r", " ")
                # 清理多余的空格
                row[key] = " ".join(row[key].split())

    # 保存
    print(f"\n{'='*70}")
    print(f"保存到: {output_file}")
    print(f"统计: 更新 {updated} 篇 | 跳过 {skipped} 篇（已完整）\n")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        if rows:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"✅ 完成!")


if __name__ == "__main__":
    main()
