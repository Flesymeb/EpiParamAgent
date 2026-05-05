"""
PubMed数据管理工具 - 统一处理PubMed数据的获取和更新

功能：
1. 根据PMID列表补充论文元数据到CSV
2. 为现有CSV补全abstract字段
3. 批量获取论文详细信息
4. 修复缺失字段（abstract/keywords等）

使用示例：
    # 补充遗漏的论文
    python pubmed_manager.py append --pmids 12345,67890 --output search.csv

    # 补全abstract
    python pubmed_manager.py enrich-abstracts --input search.csv --output search_with_abstracts.csv

    # 批量获取论文信息
    python pubmed_manager.py fetch --pmids 12345,67890 --output papers.csv

    # 修复缺失的abstract/keywords
    python pubmed_manager.py fix-missing --input search.csv --output search_fixed.csv
"""

import os
import sys
import csv
import time
import argparse
from pathlib import Path
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

import requests

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tools.pubmed.client import PubMedClient


def _fetch_pubmed_details_with_keywords(
    pmid: str, api_key: Optional[str] = None
) -> Dict[str, str]:
    """Fetch details (including keywords) for a single PMID via EFetch."""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            return {}

        root = ET.fromstring(response.content)
        article = root.find(".//PubmedArticle")
        if article is None:
            return {}

        medline = article.find(".//MedlineCitation")
        if medline is None:
            return {}
        article_elem = medline.find(".//Article")
        if article_elem is None:
            return {}

        title_elem = article_elem.find(".//ArticleTitle")
        title = "".join(title_elem.itertext()) if title_elem is not None else ""

        abstract_parts = []
        abstract_node = article_elem.find(".//Abstract")
        if abstract_node is not None:
            for abstract_text in abstract_node.findall(".//AbstractText"):
                label = abstract_text.get("Label", "")
                text = "".join(abstract_text.itertext()).strip()
                if text:
                    abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        authors = []
        for author in article_elem.findall(".//Author"):
            last = author.findtext("LastName", "")
            init = author.findtext("Initials", "")
            if last:
                authors.append(f"{last} {init}".strip())
        first_author = authors[0].split()[0] if authors else ""

        journal = article_elem.findtext(".//Journal/Title", "")
        year = ""
        pub_date = article_elem.find(".//Journal/JournalIssue/PubDate")
        if pub_date is not None:
            year = pub_date.findtext("Year", "") or ""
            if not year:
                medline_date = pub_date.findtext("MedlineDate", "") or ""
                year = medline_date[:4] if len(medline_date) >= 4 else ""

        doi = ""
        for id_elem in article_elem.findall(".//ELocationID"):
            if id_elem.get("EIdType") == "doi":
                doi = id_elem.text or ""
                break

        keyword_terms = []
        keyword_list = medline.find(".//KeywordList")
        if keyword_list is not None:
            for kw in keyword_list.findall(".//Keyword"):
                if kw.text:
                    keyword_terms.append(kw.text.strip())
        mesh_terms = []
        mesh_list = medline.find(".//MeshHeadingList")
        if mesh_list is not None:
            for mesh in mesh_list.findall(".//MeshHeading"):
                descriptor = mesh.find(".//DescriptorName")
                if descriptor is not None and descriptor.text:
                    mesh_terms.append(f"[MeSH] {descriptor.text.strip()}")
        keywords = keyword_terms if keyword_terms else mesh_terms
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
        print(f"[ERROR] {str(e)[:50]}")
        return {}


def _parse_pubmed_article_details(article: ET.Element) -> Dict[str, str]:
    medline = article.find(".//MedlineCitation")
    if medline is None:
        return {}
    article_elem = medline.find(".//Article")
    if article_elem is None:
        return {}

    pmid = article.findtext(".//PMID") or ""

    title_elem = article_elem.find(".//ArticleTitle")
    title = "".join(title_elem.itertext()) if title_elem is not None else ""

    abstract_parts = []
    abstract_node = article_elem.find(".//Abstract")
    if abstract_node is not None:
        for abstract_text in abstract_node.findall(".//AbstractText"):
            label = abstract_text.get("Label", "")
            text = "".join(abstract_text.itertext()).strip()
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = " ".join(abstract_parts)

    authors = []
    for author in article_elem.findall(".//Author"):
        last = author.findtext("LastName", "")
        init = author.findtext("Initials", "")
        if last:
            authors.append(f"{last} {init}".strip())
    first_author = authors[0].split()[0] if authors else ""

    journal = article_elem.findtext(".//Journal/Title", "")
    year = ""
    pub_date = article_elem.find(".//Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year = pub_date.findtext("Year", "") or ""
        if not year:
            medline_date = pub_date.findtext("MedlineDate", "") or ""
            year = medline_date[:4] if len(medline_date) >= 4 else ""

    doi = ""
    for id_elem in article_elem.findall(".//ELocationID"):
        if id_elem.get("EIdType") == "doi":
            doi = id_elem.text or ""
            break

    keyword_terms = []
    keyword_list = medline.find(".//KeywordList")
    if keyword_list is not None:
        for kw in keyword_list.findall(".//Keyword"):
            if kw.text:
                keyword_terms.append(kw.text.strip())
    mesh_terms = []
    mesh_list = medline.find(".//MeshHeadingList")
    if mesh_list is not None:
        for mesh in mesh_list.findall(".//MeshHeading"):
            descriptor = mesh.find(".//DescriptorName")
            if descriptor is not None and descriptor.text:
                mesh_terms.append(f"[MeSH] {descriptor.text.strip()}")
    keywords = keyword_terms if keyword_terms else mesh_terms
    keywords_str = "; ".join(keywords) if keywords else ""
    mesh_terms_str = "; ".join(mesh_terms) if mesh_terms else ""

    # Extract Publication Types (e.g., "Journal Article", "Observational Study", "Review")
    pub_types: list[str] = []
    pub_type_list = article_elem.find(".//PublicationTypeList")
    if pub_type_list is not None:
        for pt in pub_type_list.findall(".//PublicationType"):
            if pt.text:
                pub_types.append(pt.text.strip())
    pub_types_str = "; ".join(pub_types) if pub_types else ""

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "first_author": first_author,
        "authors": ", ".join(authors),
        "year": year,
        "journal": journal,
        "doi": doi,
        "keywords": keywords_str,
        "mesh_terms": mesh_terms_str,
        "pub_types": pub_types_str,
    }


def _fetch_pubmed_details_with_keywords_batch(
    pmids: List[str], api_key: Optional[str] = None
) -> Dict[str, Dict[str, str]]:
    """Fetch details (including keywords) for multiple PMIDs via EFetch."""
    if not pmids:
        return {}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"}
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            return {}

        root = ET.fromstring(response.content)
        results: Dict[str, Dict[str, str]] = {}
        for article in root.findall(".//PubmedArticle"):
            details = _parse_pubmed_article_details(article)
            pmid = details.get("pmid") or ""
            if pmid:
                results[pmid] = details
        return results
    except Exception as e:
        print(f"[ERROR] {str(e)[:50]}")
        return {}


def _normalize_title(title: str) -> str:
    if not title:
        return ""
    import re

    title = title.lower()
    title = re.sub(r"[^\w\s]", " ", title)
    return " ".join(title.split())


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _esearch(term: str, api_key: Optional[str] = None, retmax: int = 5) -> List[str]:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []


def _verify_pmid_title(
    pmid: str, expected_title: str, api_key: Optional[str] = None
) -> bool:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return False
        data = resp.json()
        actual_title = data.get("result", {}).get(pmid, {}).get("title", "")
        if not actual_title:
            return False
        excluded_prefixes = [
            "Author Correction:",
            "Correction:",
            "Erratum:",
            "Retraction:",
            "Retracted:",
            "Comment on:",
        ]
        if any(actual_title.startswith(prefix) for prefix in excluded_prefixes):
            return False
        return _title_similarity(expected_title, actual_title) > 0.95
    except Exception:
        return False


def _search_title_to_pmid(
    title: str, api_key: Optional[str] = None, verify: bool = True
) -> str:
    for word_count in [12, 8, 5]:
        words = [w for w in title.split() if len(w) > 3][:word_count]
        if len(words) < 3:
            continue
        query = " ".join(words) + "[Title]"
        pmids = _esearch(query, api_key=api_key, retmax=5)
        if not pmids:
            continue
        if verify:
            for pmid in pmids:
                if _verify_pmid_title(pmid, title, api_key=api_key):
                    return pmid
        else:
            return pmids[0]
    return ""


def _empty_pubmed_row() -> Dict[str, str]:
    return {
        "PMID": "",
        "Title": "",
        "Authors": "",
        "Citation": "",
        "First Author": "",
        "Journal/Book": "",
        "Publication Year": "",
        "Create Date": "",
        "PMCID": "",
        "NIHMS ID": "",
        "DOI": "",
        "Abstract": "",
    }


def _load_values(
    input_file: Path, default_column: str, column: Optional[str]
) -> List[str]:
    if input_file.suffix.lower() == ".csv":
        col = column or default_column
        values = []
        with open(input_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                val = (row.get(col) or "").strip()
                if val:
                    values.append(val)
        return values
    with open(input_file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def search_titles_to_csv(
    input_file: Path,
    output_file: Path,
    *,
    focus: str = "",
    verify: bool = True,
    legacy_output: bool = False,
):
    titles = _load_values(input_file, "Title", None)
    if not titles:
        print("[WARN] 未找到任何标题")
        return

    api_key = os.getenv("NCBI_API_KEY") or os.getenv("PUBMED_API_KEY")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    pmids: List[str] = []
    for i, title in enumerate(titles, 1):
        print(f"[{i:2d}] {title[:55]:55s} ", end="", flush=True)
        pmid = _search_title_to_pmid(title, api_key=api_key, verify=verify)
        if pmid:
            print(f"[OK] {pmid}")
        else:
            print("[MISS]")
        pmids.append(pmid)
        time.sleep(0.35)

    rows: List[Dict[str, str]] = []
    if legacy_output:
        for idx, title in enumerate(titles, 1):
            pmid = pmids[idx - 1]
            rows.append(
                {
                    "PMID": pmid,
                    "id": str(idx),
                    "first_author": "",
                    "year": "",
                    "title": title,
                    "journal": "",
                    "variant_focus": focus,
                    "study_type": "",
                    "country_region": "",
                    "doi_or_url": "",
                }
            )
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
    else:
        pmid_set = {p for p in pmids if p}
        details_map: Dict[str, Dict[str, str]] = {}
        if pmid_set:
            client = PubMedClient()
            details = fetch_paper_details(list(pmid_set), client)
            details_map = {d.get("PMID", ""): d for d in details}
        for idx, title in enumerate(titles, 1):
            pmid = pmids[idx - 1]
            if pmid and pmid in details_map:
                row = dict(details_map[pmid])
            else:
                row = _empty_pubmed_row()
                row["PMID"] = pmid
                row["Title"] = title
            if focus:
                row["variant_focus"] = focus
            rows.append(row)
        if rows and "Keywords" not in rows[0]:
            for row in rows:
                row["Keywords"] = ""
        fieldnames = list(rows[0].keys())

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[OK] 输出: {output_file}")


def search_dois_to_csv(
    input_file: Path,
    output_file: Path,
    *,
    column: Optional[str] = None,
    legacy_output: bool = False,
):
    dois = _load_values(input_file, "DOI", column)
    if not dois:
        print("[WARN] 未找到任何DOI")
        return

    api_key = os.getenv("NCBI_API_KEY") or os.getenv("PUBMED_API_KEY")
    pmids: List[str] = []
    for i, doi in enumerate(dois, 1):
        print(f"[{i:2d}] {doi[:55]:55s} ", end="", flush=True)
        ids = _esearch(f"{doi}[DOI]", api_key=api_key, retmax=5)
        pmid = ids[0] if ids else ""
        if pmid:
            print(f"[OK] {pmid}")
        else:
            print("[MISS]")
        pmids.append(pmid)
        time.sleep(0.35)

    rows: List[Dict[str, str]] = []
    if legacy_output:
        for idx, doi in enumerate(dois, 1):
            pmid = pmids[idx - 1]
            rows.append(
                {
                    "PMID": pmid,
                    "id": str(idx),
                    "first_author": "",
                    "year": "",
                    "title": "",
                    "journal": "",
                    "variant_focus": "",
                    "study_type": "",
                    "country_region": "",
                    "doi_or_url": doi,
                }
            )
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
    else:
        pmid_set = {p for p in pmids if p}
        details_map: Dict[str, Dict[str, str]] = {}
        if pmid_set:
            client = PubMedClient()
            details = fetch_paper_details(list(pmid_set), client)
            details_map = {d.get("PMID", ""): d for d in details}
        for idx, doi in enumerate(dois, 1):
            pmid = pmids[idx - 1]
            if pmid and pmid in details_map:
                row = dict(details_map[pmid])
            else:
                row = _empty_pubmed_row()
                row["PMID"] = pmid
            row["DOI"] = doi or row.get("DOI", "")
            rows.append(row)
        if rows and "Keywords" not in rows[0]:
            for row in rows:
                row["Keywords"] = ""
        fieldnames = list(rows[0].keys())

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[OK] 输出: {output_file}")


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
        print(f"[SKIP] 所有PMID已存在于 {csv_file.name}")
        return

    print(f"[INFO] 获取 {len(new_pmids)} 篇新论文...")
    new_papers = fetch_paper_details(new_pmids, client)

    if not new_papers:
        print("[ERROR] 未获取到任何论文数据")
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
            print(f"  [OK] {paper['PMID']}: {paper['Title'][:60]}...")

    print(f"[OK] 成功追加 {len(new_papers)} 篇论文到 {csv_file.name}")


def enrich_with_abstracts(input_csv: Path, output_csv: Path, client: PubMedClient):
    """为CSV文件补全abstract字段"""
    print(f"[INFO] 读取 {input_csv.name}...")
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
        print("[SKIP] 所有论文都已有abstract!")
        if input_csv != output_csv:
            import shutil

            shutil.copy(input_csv, output_csv)
        return

    print(f"[INFO] 需要补全abstract: {len(missing_abstract)} 篇")

    # 获取abstracts
    fetched_papers = fetch_paper_details(missing_abstract, client)
    pmid_to_abstract = {p["PMID"]: p["Abstract"] for p in fetched_papers}

    # 更新papers
    for paper in papers:
        pmid = paper.get("PMID", "").strip()
        if pmid in pmid_to_abstract:
            paper["Abstract"] = pmid_to_abstract[pmid]
            print(f"  [OK] {pmid}: abstract长度 {len(pmid_to_abstract[pmid])} 字符")

    # 写入输出文件
    if papers:
        fieldnames = list(papers[0].keys())
        if "Abstract" not in fieldnames:
            fieldnames.append("Abstract")

        with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(papers)

    print(f"[OK] 已保存到 {output_csv.name}")


def batch_fetch(pmids: List[str], output_csv: Path, client: PubMedClient):
    """批量获取论文并保存到新CSV"""
    print(f"[INFO] 获取 {len(pmids)} 篇论文...")
    papers = fetch_paper_details(pmids, client)

    if not papers:
        print("[ERROR] 未获取到任何论文数据")
        return

    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(papers[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    print(f"[OK] 成功保存 {len(papers)} 篇论文到 {output_csv.name}")


def fix_missing_fields(input_csv: Path, output_csv: Path):
    """修复CSV中缺失的abstract/keywords等字段."""
    print(f"[INFO] 读取 {input_csv.name}...")
    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("[WARN] 输入为空，退出")
        return

    if "Keywords" not in rows[0]:
        for row in rows:
            row["Keywords"] = ""

    api_key = os.getenv("NCBI_API_KEY") or os.getenv("PUBMED_API_KEY")
    verbose = os.getenv("PUBMED_FIXMISSING_VERBOSE", "1") != "0"
    batch_sleep_s = float(os.getenv("PUBMED_BATCH_SLEEP_S", "0") or "0")

    def _chunk(items: List[str], size: int):
        for i in range(0, len(items), size):
            yield items[i : i + size]

    missing_pmids = []
    for row in rows:
        pmid = row.get("PMID", "").strip()
        if not pmid:
            continue
        abstract = row.get("Abstract", "").strip()
        keywords = row.get("Keywords", "").strip()
        if not (abstract and keywords):
            missing_pmids.append(pmid)

    missing_pmids = list(dict.fromkeys(missing_pmids))
    if missing_pmids:
        print(f"[INFO] 需要补全字段: {len(missing_pmids)} 篇")
    else:
        print("[INFO] 无需补全字段")

    details_map: Dict[str, Dict[str, str]] = {}
    chunks = list(_chunk(missing_pmids, 200))
    total_chunks = len(chunks)
    if missing_pmids:
        print(f"[INFO] 批量拉取 PubMed 详情: {len(missing_pmids)} PMID(s), {total_chunks} 批")
    for idx, chunk in enumerate(chunks, 1):
        if verbose:
            print(f"[INFO] PubMed 批次 {idx}/{total_chunks} (n={len(chunk)})")
        details_map.update(
            _fetch_pubmed_details_with_keywords_batch(chunk, api_key=api_key)
        )
        if batch_sleep_s > 0 and idx < total_chunks:
            time.sleep(batch_sleep_s)

    updated = 0
    skipped = 0
    for i, row in enumerate(rows, 1):
        pmid = row.get("PMID", "").strip()
        if not pmid:
            print(f"[{i:2d}] [SKIP] 无PMID，跳过")
            continue

        abstract = row.get("Abstract", "").strip()
        keywords = row.get("Keywords", "").strip()
        if abstract and keywords:
            skipped += 1
            continue

        missing = []
        if not abstract:
            missing.append("摘要")
        if not keywords:
            missing.append("Keywords")

        if verbose:
            print(f"[{i:2d}] [INFO] PMID {pmid} [缺少: {', '.join(missing)}] ", end="")
        details = details_map.get(pmid, {})
        if details:
            row["Title"] = details.get("title") or row.get("Title", "")
            row["First Author"] = details.get("first_author") or row.get(
                "First Author", ""
            )
            row["Publication Year"] = details.get("year") or row.get(
                "Publication Year", ""
            )
            row["Journal/Book"] = details.get("journal") or row.get("Journal/Book", "")
            row["DOI"] = details.get("doi") or row.get("DOI", "")

            if not abstract:
                row["Abstract"] = details.get("abstract", "")
            if not keywords:
                row["Keywords"] = details.get("keywords", "")

            if verbose:
                print(
                    f"[OK] {details.get('first_author', '')} ({details.get('year', '')})"
                )
            updated += 1
        else:
            if verbose:
                print("[WARN] 获取失败")

    for row in rows:
        for key in row.keys():
            if isinstance(row[key], str):
                row[key] = " ".join(
                    row[key].replace("\n", " ").replace("\r", " ").split()
                )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[OK] 保存到 {output_csv.name} (更新 {updated} | 跳过 {skipped})")


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
    # fix-missing命令
    fix_parser = subparsers.add_parser("fix-missing", help="修复缺失字段")
    fix_parser.add_argument("--input", required=True, help="输入CSV文件")
    fix_parser.add_argument("--output", required=True, help="输出CSV文件")
    # search-title命令
    title_parser = subparsers.add_parser("search-title", help="根据标题搜索PMID")
    title_parser.add_argument("--input", required=True, help="标题列表文件(.txt或.csv)")
    title_parser.add_argument("--output", required=True, help="输出CSV文件")
    title_parser.add_argument(
        "--focus",
        default="",
        help="可选：研究焦点标签(写入variant_focus字段，非legacy格式)",
    )
    title_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="不校验标题匹配(默认会校验)",
    )
    title_parser.add_argument(
        "--legacy-output",
        action="store_true",
        help="使用旧版输出列格式",
    )
    # search-doi命令
    doi_parser = subparsers.add_parser("search-doi", help="根据DOI搜索PMID")
    doi_parser.add_argument("--input", required=True, help="DOI列表文件(.txt或.csv)")
    doi_parser.add_argument("--output", required=True, help="输出CSV文件")
    doi_parser.add_argument(
        "--column",
        default=None,
        help="如果输入是CSV，指定DOI列名(默认DOI)",
    )
    doi_parser.add_argument(
        "--legacy-output",
        action="store_true",
        help="使用旧版输出列格式",
    )

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
    elif args.command == "fix-missing":
        input_file = Path(args.input)
        output_file = Path(args.output)
        fix_missing_fields(input_file, output_file)
    elif args.command == "search-title":
        input_file = Path(args.input)
        output_file = Path(args.output)
        search_titles_to_csv(
            input_file,
            output_file,
            focus=args.focus,
            verify=not args.no_verify,
            legacy_output=args.legacy_output,
        )
    elif args.command == "search-doi":
        input_file = Path(args.input)
        output_file = Path(args.output)
        search_dois_to_csv(
            input_file,
            output_file,
            column=args.column,
            legacy_output=args.legacy_output,
        )


if __name__ == "__main__":
    main()
