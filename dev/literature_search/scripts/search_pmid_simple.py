#!/usr/bin/env python3
"""
使用PubMed E-utilities直接搜索（不依赖PubMedClient）
"""

import csv
import time
import requests
import argparse
from pathlib import Path
from urllib.parse import quote
from difflib import SequenceMatcher


def title_similarity(a: str, b: str) -> float:
    """计算两个标题的相似度 (0-1)"""
    a_clean = a.lower().strip()
    b_clean = b.lower().strip()
    return SequenceMatcher(None, a_clean, b_clean).ratio()


def verify_pmid_title(pmid: str, expected_title: str) -> tuple[bool, str]:
    """
    验证PMID对应的标题是否匹配预期标题
    返回 (是否匹配, 实际标题)
    """
    try:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {"db": "pubmed", "id": pmid, "retmode": "json"}
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            actual_title = data["result"][pmid]["title"]

            # 排除 correction/erratum/retraction
            excluded_prefixes = [
                "Author Correction:",
                "Correction:",
                "Erratum:",
                "Retraction:",
                "Retracted:",
                "Comment on:",
            ]
            if any(actual_title.startswith(prefix) for prefix in excluded_prefixes):
                return (False, actual_title)

            similarity = title_similarity(expected_title, actual_title)
            # 相似度>0.8认为匹配（提高阈值）
            return (similarity > 0.95, actual_title)
    except Exception:
        pass

    return (False, "")


def search_pubmed_simple(title: str, api_key: str = None, verify: bool = True) -> str:
    """
    简化版PubMed搜索，返回PMID
    """
    # 尝试不同长度的查询
    for word_count in [12, 8, 5]:
        words = [w for w in title.split() if len(w) > 3][:word_count]
        if len(words) < 3:
            continue

        query = " ".join(words) + "[Title]"

        # ESearch API
        base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "pubmed", "term": query, "retmax": 5, "retmode": "json"}
        if api_key:
            params["api_key"] = api_key

        try:
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                pmid_list = data.get("esearchresult", {}).get("idlist", [])

                if not pmid_list:
                    continue

                # 如果需要验证，检查返回的PMID
                if verify:
                    for pmid in pmid_list:
                        is_match, actual_title = verify_pmid_title(pmid, title)
                        if is_match:
                            return pmid
                else:
                    return pmid_list[0]
        except Exception as e:
            if word_count == 5:  # 最后一次尝试才报错
                print(f"      搜索错误: {str(e)[:50]}")

    return ""


def main():
    parser = argparse.ArgumentParser(description="根据标题列表搜索PubMed PMID")
    parser.add_argument("--input", required=True, help="标题列表文件(title.txt)")
    parser.add_argument("--output", required=True, help="输出CSV文件")
    parser.add_argument("--focus", default="Serial interval", help="研究焦点")
    args = parser.parse_args()

    titles_file = Path(args.input)
    output_file = Path(args.output)

    print(f"读取标题: {titles_file}\n")

    with open(titles_file, "r", encoding="utf-8") as f:
        titles = [line.strip() for line in f if line.strip()]

    print(f"共 {len(titles)} 篇论文\n")

    results = []
    found_count = 0

    for i, title in enumerate(titles, 1):
        print(f"[{i:2d}] {title[:55]:55s} ", end="", flush=True)

        pmid = search_pubmed_simple(title)

        if pmid:
            print(f"✓ {pmid}")
            found_count += 1
        else:
            print(f"✗")

        results.append(
            {
                "PMID": pmid,
                "id": i,
                "first_author": "",
                "year": "",
                "title": title,
                "journal": "",
                "variant_focus": args.focus,
                "study_type": "",
                "country_region": "",
                "doi_or_url": "",
            }
        )

        time.sleep(0.35)

    # 保存CSV
    print(f"\n{'='*70}")
    print(f"保存到: {output_file}")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "PMID",
            "id",
            "first_author",
            "year",
            "title",
            "journal",
            "variant_focus",
            "study_type",
            "country_region",
            "doi_or_url",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(
        f"\n✅ 完成! 找到 {found_count}/{len(results)} 篇PMID ({found_count/len(results)*100:.1f}%)"
    )
    print(f"\n💡 下一步：")
    print(
        f"   python pubmed_manager.py enrich-abstracts --input {args.output} --output {args.output}"
    )


if __name__ == "__main__":
    main()
