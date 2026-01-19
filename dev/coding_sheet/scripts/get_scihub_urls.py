"""Extract and verify PDF URLs from Sci-Hub using DOI list.

Reads DOIs from papers/doi.txt, resolves them to PDF URLs from multiple mirrors,
tests each URL for accessibility, and saves results in JSONL format.

Usage:
    python scripts/get_scihub_urls.py

Input:
    papers/doi.txt - One DOI per line (e.g., 10.1177/1534508409346053)

Output:
    papers/scihub_urls.jsonl - JSONL format with DOI, multiple URLs, and status

JSONL Format:
    {"doi": "10.xxx/yyy", "urls": [{"url": "https://...", "status": "available", "size": 1234567}]}

Author: Hyoung Yan
Created: 2025-12-25
Modified: 2026-01-08
"""

# TODO
# IMPORTANT: This script is for educational/research purposes only.
# Please respect copyright and publisher policies.

import cloudscraper
import requests
from bs4 import BeautifulSoup
import os
import time
import sys
import re
import json
import random
from termcolor import cprint
from urllib.parse import urljoin
from pathlib import Path
from fake_useragent import UserAgent

try:
    from script_utils import safe_slug
except ImportError:

    def safe_slug(s):
        return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


class SciHubUrlExtractor:
    def __init__(self):
        # Configure proxy if environment variable is set
        proxies = None
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http_proxy or https_proxy:
            proxies = {}
            if http_proxy:
                proxies["http"] = http_proxy
            if https_proxy:
                proxies["https"] = https_proxy
            cprint(f"Using proxy: {proxies}", "cyan")

        # Use cloudscraper to bypass DDoS-Guard/Cloudflare protection
        self.sess = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        if proxies:
            self.sess.proxies.update(proxies)

        self.ua = UserAgent()
        # Set initial headers with random user agent
        self.sess.headers.update(self._get_random_headers())
        self.mirrors = []

        # Check if Playwright is available for advanced bypass
        try:
            from playwright.sync_api import sync_playwright

            self.has_playwright = True
            self._playwright = sync_playwright
        except ImportError:
            self.has_playwright = False
            self._playwright = None
            cprint(
                "Note: Playwright not available. Install with: pip install playwright; playwright install chromium",
                "yellow",
            )

    def _get_random_headers(self):
        """Generate realistic browser headers with random user agent."""
        return {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    def get_mirrors(self):
        """Fetch active Sci-Hub mirrors from sci-hub.pub with cloudscraper bypass."""
        cprint("Fetching active Sci-Hub mirrors from sci-hub.pub...", "cyan")

        try:
            resp = self.sess.get("https://sci-hub.pub", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=True)

            for link in links:
                href = link["href"]
                if href.startswith("https://sci-hub.") and href not in self.mirrors:
                    self.mirrors.append(href.rstrip("/"))

            # 确保sci.bban.top始终排在第一位（最快，直接PDF）
            if "https://sci.bban.top" not in self.mirrors:
                self.mirrors.insert(0, "https://sci.bban.top")
            elif self.mirrors[0] != "https://sci.bban.top":
                self.mirrors.remove("https://sci.bban.top")
                self.mirrors.insert(0, "https://sci.bban.top")

            if not self.mirrors:
                cprint(
                    "No mirrors found from sci-hub.pub, using fallback list...",
                    "yellow",
                )
                self.mirrors = [
                    "https://sci.bban.top",
                    "https://sci-hub.se",
                    "https://sci-hub.st",
                    "https://sci-hub.ru",
                ]

            cprint(
                f"Found {len(self.mirrors)} mirrors (priority: sci.bban.top first): {', '.join(self.mirrors)}",
                "green",
            )
        except Exception as e:
            cprint(f"Failed to fetch mirrors: {e}", "red")
            cprint("Using fallback mirror list...", "yellow")
            # sci.bban.top优先 - 直接PDF格式，无需DDoS-Guard bypass
            self.mirrors = [
                "https://sci.bban.top",
                "https://sci-hub.se",
                "https://sci-hub.st",
                "https://sci-hub.ru",
            ]
            cprint(f"Fallback mirrors: {', '.join(self.mirrors)}", "green")

    def _random_delay(self, min_sec=0.5, max_sec=2.0):
        """Random delay to avoid detection."""
        time.sleep(random.uniform(min_sec, max_sec))

    def get_pdf_url(self, doi, base_url, download_dir=None):
        """Extract PDF download link from Sci-Hub page using cloudscraper.

        Tries multiple methods to find PDF URL:
        1. Direct PDF URL format (sci.bban.top: /pdf/DOI.pdf)
        2. <embed src="..."> tag
        3. <iframe src="..."> tag
        4. <button onclick="..."> with PDF link
        5. (Fallback) Playwright browser automation if cloudscraper gets 403

        Args:
            doi: DOI string
            base_url: Sci-Hub mirror URL
            download_dir: Directory to save PDF (if provided, download in Playwright session)

        Returns:
            tuple: (url_or_path, from_playwright, download_url)
                - url_or_path: A resolvable PDF URL, or a local file path if downloaded via Playwright
                - from_playwright: True if obtained via Playwright
                - download_url: The actual PDF download URL when known (best-effort)
        """
        # Special handling for sci.bban.top - direct PDF format
        if "bban.top" in base_url:
            pdf_url = f"{base_url}/pdf/{doi}.pdf"
            cprint(f"  → Direct PDF URL: {pdf_url}", "cyan")
            return (pdf_url, False, pdf_url)

        # For traditional Sci-Hub mirrors, scrape the page
        page_url = f"{base_url}/{doi}"

        try:
            # Random delay before request
            self._random_delay(0.3, 0.8)

            # Update referer for this request
            headers = self._get_random_headers()
            headers["Referer"] = base_url + "/"

            resp = self.sess.get(page_url, headers=headers, timeout=15)

            if resp.status_code == 403:
                cprint(
                    f"  ⚠ HTTP 403 from cloudscraper, trying Playwright...", "yellow"
                )
                return self._get_pdf_url_with_playwright(
                    page_url, base_url, doi, download_dir
                )

            if resp.status_code != 200:
                cprint(f"  ✗ HTTP {resp.status_code} for {page_url}", "red")
                return (None, False, None)

            soup = BeautifulSoup(resp.text, "html.parser")

            # Method 1: <div class="download"><a href="/download/.../*.pdf">
            download_div = soup.find("div", class_="download")
            if download_div:
                link = download_div.find("a", href=True)
                if link and link["href"]:
                    pdf_url = urljoin(base_url, link["href"])
                    cprint(f"  → Found via <div.download>: {pdf_url}", "green")
                    return (pdf_url, False, pdf_url)

            # Method 2: <embed src="...">
            embed = soup.find("embed", src=True)
            if embed and embed["src"]:
                pdf_url = urljoin(base_url, embed["src"])
                if pdf_url.endswith(".pdf") or "pdf" in pdf_url.lower():
                    cprint(f"  → Found via <embed>: {pdf_url}", "green")
                    return (pdf_url, False, pdf_url)

            # Method 3: <iframe src="...">
            iframe = soup.find("iframe", src=True)
            if iframe and iframe["src"]:
                pdf_url = urljoin(base_url, iframe["src"])
                if pdf_url.endswith(".pdf") or "pdf" in pdf_url.lower():
                    cprint(f"  → Found via <iframe>: {pdf_url}", "green")
                    return (pdf_url, False, pdf_url)

            # Method 4: <button onclick="..."> or <a href="...">
            for button in soup.find_all(["button", "a"], href=True):
                href = button.get("href", "")
                onclick = button.get("onclick", "")
                combined = href + " " + onclick

                if ".pdf" in combined.lower() or "download" in combined.lower():
                    # Extract URL from onclick or href
                    match = re.search(r"(https?://[^\s'\"]+\.pdf)", combined)
                    if match:
                        pdf_url = match.group(1)
                        cprint(f"  → Found via button/link: {pdf_url}", "green")
                        return (pdf_url, False, pdf_url)

            cprint(f"  ✗ No PDF URL found in page", "yellow")
            return (None, False, None)

        except Exception as e:
            cprint(f"  ✗ Error scraping {page_url}: {e}", "red")
            return (None, False, None)

    def _get_pdf_url_with_playwright(
        self, page_url, base_url, doi=None, download_dir=None
    ):
        """Fallback: Use Playwright to bypass DDoS-Guard and download PDF directly.

        Opens a browser window (non-headless) for manual interaction if automated
        extraction fails. Downloads PDF within browser session to avoid cookie issues.

        Args:
            page_url: Sci-Hub page URL to visit
            base_url: Base URL for resolving relative links
            doi: DOI string for filename generation (optional)
            download_dir: Directory to save PDF (if None, only extract URL)

        Returns:
            tuple: (pdf_path_or_url, from_playwright, download_url)
        """
        if not self.has_playwright:
            cprint(f"  ✗ Playwright not available, cannot bypass", "red")
            return (None, False, None)

        try:
            with self._playwright() as p:
                # Launch in non-headless mode with larger window for better visibility
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        "--no-sandbox",
                        "--start-maximized",  # Start maximized
                    ],
                )

                # Set download directory if provided
                context_kwargs = {
                    "user_agent": self.ua.random,
                    "viewport": None,  # Use full screen instead of fixed size
                    "no_viewport": True,  # Allow window to be resizable
                }
                if download_dir:
                    download_dir = Path(download_dir)
                    download_dir.mkdir(parents=True, exist_ok=True)
                    context_kwargs["accept_downloads"] = True

                context = browser.new_context(**context_kwargs)
                page = context.new_page()

                # Track download
                downloaded_file = None
                pdf_url_from_download = None
                actual_download_url = None  # 记录真实下载URL

                def handle_download(download):
                    nonlocal downloaded_file, pdf_url_from_download, actual_download_url
                    pdf_url_from_download = download.url
                    actual_download_url = download.url  # 保存真实URL
                    cprint(
                        f"  ✓ Captured download URL: {pdf_url_from_download}", "green"
                    )

                    # Save PDF if download_dir provided
                    if download_dir and doi:
                        safe_doi = safe_slug(doi)
                        save_path = download_dir / f"{safe_doi}.pdf"
                        download.save_as(str(save_path))
                        downloaded_file = save_path
                        cprint(f"  ✓ Saved PDF to: {save_path}", "green")

                page.on("download", handle_download)

                cprint(f"  → Opening browser window for manual interaction...", "cyan")
                cprint(
                    f"  → Please click the download button if challenge appears",
                    "yellow",
                )
                page.goto(page_url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # First try automated extraction and click
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Method 1: Find <div class="download"><a> and click it
                download_div = soup.find("div", class_="download")
                if download_div:
                    link = download_div.find("a", href=True)
                    if link and link["href"]:
                        pdf_url = urljoin(base_url, link["href"])
                        cprint(f"  ✓ Found download link: {pdf_url}", "green")

                        # If download_dir provided, click to download in browser
                        if download_dir:
                            try:
                                # Find and click the download button
                                selector = "div.download a"
                                if page.locator(selector).count() > 0:
                                    cprint(f"  → Clicking download link...", "cyan")
                                    page.locator(selector).first.click()
                                    page.wait_for_timeout(
                                        2000
                                    )  # Wait for download to start
                            except Exception as e:
                                cprint(f"  ⚠ Auto-click failed: {e}", "yellow")
                        else:
                            # Just return URL if no download_dir
                            browser.close()
                            return (pdf_url, True, pdf_url)

                # If automated click failed, wait for manual download
                if not downloaded_file and download_dir:
                    cprint(
                        f"  ⚠ Automated download didn't trigger. Browser window is open.",
                        "yellow",
                    )
                    cprint(f"  → Please manually click the download button", "yellow")
                    cprint(f"  → Waiting for download event (60s timeout)...", "cyan")

                    try:
                        page.wait_for_event("download", timeout=60000)
                    except Exception:
                        cprint(f"  ✗ No download detected within timeout", "red")

                browser.close()

                # Return downloaded file path or URL, plus actual download URL
                if downloaded_file and downloaded_file.exists():
                    return (str(downloaded_file), True, actual_download_url)
                elif pdf_url_from_download:
                    return (pdf_url_from_download, True, pdf_url_from_download)

                cprint(f"  ✗ No PDF downloaded or URL captured", "red")
                return (None, False, None)

        except Exception as e:
            cprint(f"  ✗ Playwright bypass failed: {e}", "red")
            return (None, False, None)

    def test_url(self, url):
        """Test if URL is accessible and return status info."""
        try:
            # Use random headers for testing
            headers = self._get_random_headers()
            # Extract domain for referer
            from urllib.parse import urlparse

            parsed = urlparse(url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

            resp = self.sess.head(
                url, headers=headers, timeout=10, allow_redirects=True
            )
            if resp.status_code == 200:
                size = resp.headers.get("Content-Length")
                return {
                    "status": "available",
                    "code": 200,
                    "size": int(size) if size else None,
                }
            else:
                return {
                    "status": "unavailable",
                    "code": resp.status_code,
                    "size": None,
                }
        except requests.exceptions.Timeout:
            return {"status": "timeout", "code": None, "size": None}
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            return {
                "status": "error",
                "code": None,
                "size": None,
                "error": "SSL/Connection error",
            }
        except Exception as e:
            return {"status": "error", "code": None, "size": None, "error": str(e)}

    def _try_pubmed_fulltext(self, doi):
        """Try to get full-text PDF from PubMed Central if available.

        Returns:
            str or None: PDF URL if found, None otherwise
        """
        try:
            # Check if PMC has full-text via NCBI E-utilities
            from urllib.parse import quote

            search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pmc&term={quote(doi)}&retmode=json"

            resp = self.sess.get(search_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                id_list = data.get("esearchresult", {}).get("idlist", [])

                if id_list:
                    pmc_id = id_list[0]
                    cprint(f"  → Found PMC full-text: PMC{pmc_id}", "green")

                    # Visit HTML page to parse actual PDF link (path is not fixed)
                    html_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_id}/"
                    html_resp = self.sess.get(html_url, timeout=10)

                    if html_resp.status_code == 200:
                        soup = BeautifulSoup(html_resp.text, "html.parser")

                        # Find PDF download link: <a href="pdf/...pdf">
                        pdf_links = soup.find_all("a", href=True)
                        for link in pdf_links:
                            href = link["href"]
                            if href.endswith(".pdf") or "/pdf/" in href:
                                # Convert relative path to absolute URL
                                pdf_url = urljoin(html_url, href)
                                cprint(f"  → PMC PDF link: {pdf_url}", "cyan")
                                return pdf_url

                        # Fallback: try common patterns
                        # Some PMCs use /pdf/main.pdf, others use pdf/{article-name}.pdf
                        for pattern in ["pdf/main.pdf", f"pdf/PMC{pmc_id}.pdf"]:
                            pdf_url = urljoin(html_url, pattern)
                            cprint(f"  → Trying fallback: {pdf_url}", "yellow")
                            return pdf_url

        except Exception as e:
            pass  # Silently fail, will try Sci-Hub

        return None

    def process_doi(self, doi, download_dir=None):
        """Resolve DOI to multiple PDF URLs from different mirrors and test each.

        Priority order:
        1. PubMed Central full-text (if available)
        2. sci.bban.top (direct PDF, fastest)
        3. Other Sci-Hub mirrors

        Stops after finding the first available URL to avoid redundant testing.

        Args:
            doi: DOI string
            download_dir: Directory to save PDF (if provided, triggers Playwright download)
        """
        cprint(f"Resolving DOI: {doi}", "magenta")

        url_results = []
        seen_urls = set()
        found_available = False

        # Priority 1: Try PubMed Central first
        pmc_url = self._try_pubmed_fulltext(doi)
        pmc_download_success = False

        if pmc_url:
            # Skip test_url for PMC - HEAD request may return 200 but GET returns HTML
            # Try direct download instead
            if download_dir:
                safe_doi_name = safe_slug(doi)
                pdf_path = Path(download_dir) / f"{safe_doi_name}.pdf"

                if pdf_path.exists():
                    cprint(f"  ↓ PDF already exists: {pdf_path.name}", "yellow")
                    url_info = {
                        "url": pmc_url,
                        "download_url": pmc_url,
                        "source": "PubMed Central",
                        "status": "downloaded",
                        "local_path": str(pdf_path),
                        "code": 200,
                        "size": None,
                    }
                    url_results.append(url_info)
                    pmc_download_success = True
                else:
                    # Try downloading with retries
                    max_retries = 1  # PMC often restricts access, fail fast
                    for attempt in range(max_retries):
                        try:
                            if attempt > 0:
                                cprint(
                                    f"  ↓ Retrying PMC download (attempt {attempt + 1}/{max_retries})...",
                                    "cyan",
                                    end="",
                                )
                            else:
                                cprint(f"  ↓ Downloading from PMC...", "cyan", end="")

                            # Use browser-like headers for PMC
                            pmc_headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": "en-US,en;q=0.9",
                                "Referer": f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_url.split('PMC')[1].split('/')[0]}/",
                                "Connection": "keep-alive",
                            }

                            resp = self.sess.get(
                                pmc_url, headers=pmc_headers, timeout=30
                            )

                            # Check if response is actually a PDF
                            if resp.status_code == 200:
                                if resp.content[:4] == b"%PDF":
                                    pdf_path.write_bytes(resp.content)
                                    size_mb = len(resp.content) / 1024 / 1024
                                    cprint(f" ✓ Saved ({size_mb:.2f} MB)", "green")
                                    url_info = {
                                        "url": pmc_url,
                                        "download_url": pmc_url,
                                        "source": "PubMed Central",
                                        "status": "downloaded",
                                        "local_path": str(pdf_path),
                                        "code": 200,
                                        "size": len(resp.content),
                                    }
                                    url_results.append(url_info)
                                    pmc_download_success = True
                                    break
                                else:
                                    # Got HTML instead of PDF - PMC access restricted
                                    cprint(f" ✗ PMC access restricted", "red")
                                    break  # Don't retry, go straight to Sci-Hub
                            else:
                                cprint(f" ✗ HTTP {resp.status_code}", "red")
                                break  # Don't retry on HTTP errors

                        except (
                            requests.exceptions.ProxyError,
                            requests.exceptions.ConnectionError,
                        ) as e:
                            cprint(f" ✗ Connection error", "red")
                            break
                        except requests.exceptions.Timeout:
                            cprint(f" ✗ Timeout", "red")
                            break
                        except Exception as e:
                            cprint(f" ✗ {type(e).__name__}", "red")
                            break

                    # If download failed, show fallback message
                    if not pmc_download_success:
                        cprint(
                            f"  ⚠ HTTP download failed, trying with browser...",
                            "yellow",
                        )

                        # Try Playwright browser download for PMC
                        pmc_article_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_url.split('PMC')[1].split('/')[0]}/"
                        link_or_path, from_playwright, actual_url = (
                            self._get_pdf_url_with_playwright(
                                pmc_article_url,
                                "https://pmc.ncbi.nlm.nih.gov",
                                doi,
                                download_dir,
                            )
                        )

                        if link_or_path and Path(link_or_path).exists():
                            cprint(
                                f"  ✓ Downloaded via browser: {Path(link_or_path).name}",
                                "green",
                            )
                            url_info = {
                                "url": pmc_url,
                                "download_url": actual_url or pmc_url,
                                "source": "PubMed Central (Browser)",
                                "status": "downloaded",
                                "local_path": str(link_or_path),
                                "code": 200,
                                "size": None,
                            }
                            url_results.append(url_info)
                            pmc_download_success = True
            else:
                # No download requested, just record the URL
                url_info = {
                    "url": pmc_url,
                    "download_url": pmc_url,
                    "source": "PubMed Central",
                    "status": "available",
                    "code": 200,
                    "size": None,
                }
                url_results.append(url_info)
                pmc_download_success = True

            # Return early only if PMC download actually succeeded
            if pmc_download_success:
                return url_results

        # Priority 2-3: Try Sci-Hub mirrors if PMC failed or unavailable

        for mirror in self.mirrors:
            link_or_path, from_playwright, actual_url = self.get_pdf_url(
                doi, mirror, download_dir
            )

            if link_or_path and link_or_path not in seen_urls:
                seen_urls.add(link_or_path)

                # Check if this is a local file path (downloaded via Playwright)
                is_local_file = (
                    isinstance(link_or_path, str) and Path(link_or_path).exists()
                )

                if is_local_file:
                    cprint(f"  ✓ Downloaded to: {link_or_path}", "green")
                    url_info = {
                        "url": link_or_path,
                        "status": "downloaded",
                        "code": 200,
                        "size": None,
                        "local_path": link_or_path,
                        "download_url": actual_url,  # 记录真实下载URL
                    }
                    url_results.append(url_info)
                    found_available = True
                    cprint(f"  ✓ PDF downloaded, skipping remaining mirrors", "green")
                    break
                else:
                    cprint(f"  Found: {link_or_path}", "cyan")

                # If from Playwright (but not downloaded), skip test_url and mark as available
                if from_playwright:
                    url_info = {
                        "url": link_or_path,
                        "status": "available",
                        "code": 200,
                        "size": None,
                        "download_url": actual_url,
                    }
                    url_results.append(url_info)
                    cprint(f"  ✓ From Playwright session, marked as available", "green")
                    found_available = True
                    cprint(
                        f"  ✓ Found working URL, skipping remaining mirrors", "green"
                    )
                    break

                # Test URL availability (only for non-Playwright URLs)
                cprint(f"  Testing accessibility...", "yellow", end="")
                test_result = self.test_url(link_or_path)

                url_info = {
                    "url": link_or_path,
                    "download_url": actual_url,
                    **test_result,
                }
                url_results.append(url_info)

                if test_result["status"] == "available":
                    size_mb = (
                        test_result["size"] / 1024 / 1024 if test_result["size"] else 0
                    )
                    cprint(f" ✓ Available ({size_mb:.2f} MB)", "green")
                    found_available = True
                    cprint(
                        f"  ✓ Found working URL, skipping remaining mirrors", "green"
                    )
                    break  # Stop after finding first available URL
                else:
                    cprint(f" ✗ {test_result['status']}", "red")

            self._random_delay(0.5, 1.5)  # Random delay between mirrors

        if url_results:
            cprint(
                f"  → Found {len(url_results)} URL(s), {sum(1 for u in url_results if u['status'] in ['available', 'downloaded'])} available",
                "green",
            )
        else:
            cprint(f"  → No URLs found", "red")

        return url_results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract and verify PDF URLs from Sci-Hub"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download PDFs to papers/pdfs/ directory",
    )
    args = parser.parse_args()

    cprint("SCI-HUB URL Extractor & Verifier", "magenta", attrs=["bold"])

    extractor = SciHubUrlExtractor()
    extractor.get_mirrors()

    # Paths
    base_dir = Path(__file__).resolve().parents[1]
    papers_dir = base_dir / "papers"
    doi_file = papers_dir / "doi.txt"
    out_jsonl = papers_dir / "scihub_urls.jsonl"
    out_txt = papers_dir / "scihub_urls.txt"  # Backward compatibility
    pdf_dir = papers_dir / "pdfs"

    if args.download:
        pdf_dir.mkdir(exist_ok=True)
        cprint(f"PDF download mode enabled. Saving to: {pdf_dir}", "green")

    if not doi_file.exists():
        cprint(f"[!] doi.txt not found at {doi_file}", "red")
        sys.exit(1)

    with open(doi_file, "r") as f:
        dois = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not dois:
        cprint("No DOIs found.", "yellow")
        return

    cprint(f"Found {len(dois)} DOIs.", "cyan")

    results = []
    available_urls = []
    downloaded_pdfs = []

    for doi in dois:
        # Pass download_dir if download mode enabled
        download_target = pdf_dir if args.download else None
        url_results = extractor.process_doi(doi, download_dir=download_target)

        result = {
            "doi": doi,
            "urls": url_results,
            "available_count": sum(
                1 for u in url_results if u["status"] in ["available", "downloaded"]
            ),
            "total_count": len(url_results),
        }
        results.append(result)

        # Check if PDF was already downloaded (via PMC, Playwright, or previous runs)
        downloaded_entry = next(
            (u for u in url_results if u["status"] == "downloaded"), None
        )
        if downloaded_entry:
            pdf_path = Path(downloaded_entry.get("local_path", downloaded_entry["url"]))
            if pdf_path.exists():
                downloaded_pdfs.append(str(pdf_path))
                result["downloaded_pdf"] = str(pdf_path)
                # Already printed in process_doi(), no need to print again

        # Fallback: Download PDF if requested but not downloaded yet
        elif args.download and url_results:
            first_available = next(
                (u for u in url_results if u["status"] == "available"), None
            )
            if first_available:
                pdf_url = first_available["url"]
                safe_doi = safe_slug(doi)
                pdf_path = pdf_dir / f"{safe_doi}.pdf"

                if pdf_path.exists():
                    cprint(f"  ↓ PDF already exists: {pdf_path.name}", "yellow")
                    downloaded_pdfs.append(str(pdf_path))
                else:
                    cprint(f"  ↓ Downloading PDF via HTTP...", "cyan", end="")
                    try:
                        # Use same session with cookies from URL extraction
                        resp = extractor.sess.get(pdf_url, timeout=30)
                        if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                            pdf_path.write_bytes(resp.content)
                            size_mb = len(resp.content) / 1024 / 1024
                            cprint(
                                f" ✓ Saved {pdf_path.name} ({size_mb:.2f} MB)", "green"
                            )
                            downloaded_pdfs.append(str(pdf_path))
                            result["downloaded_pdf"] = str(pdf_path)
                        else:
                            cprint(
                                f" ✗ Failed (status={resp.status_code}, not PDF)", "red"
                            )
                    except Exception as e:
                        cprint(f" ✗ Download error: {e}", "red")

        # For backward compatibility: save first available URL
        available = [
            u["url"] for u in url_results if u["status"] in ["available", "downloaded"]
        ]
        if available:
            available_urls.append(available[0])

        # Random delay between DOIs (1-3 seconds)
        if doi != dois[-1]:  # Don't delay after last DOI
            extractor._random_delay(1.0, 3.0)

    # Save JSONL format
    if results:
        with open(out_jsonl, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        cprint(f"\n✓ Saved detailed results to {out_jsonl}", "green", attrs=["bold"])

        # Also save simple txt format for backward compatibility
        if available_urls:
            with open(out_txt, "w") as f:
                for u in available_urls:
                    f.write(u + "\n")
            cprint(
                f"✓ Saved {len(available_urls)} available URLs to {out_txt}", "green"
            )

        # Print summary
        cprint("\n" + "=" * 60, "cyan")
        cprint("Summary:", "cyan", attrs=["bold"])
        total_urls = sum(r["total_count"] for r in results)
        total_available = sum(r["available_count"] for r in results)
        cprint(f"  Total DOIs: {len(results)}", "white")
        cprint(f"  Total URLs found: {total_urls}", "white")
        cprint(f"  Available URLs: {total_available}", "green")
        cprint(f"  Unavailable URLs: {total_urls - total_available}", "red")
        if args.download:
            cprint(f"  Downloaded PDFs: {len(downloaded_pdfs)}/{len(results)}", "green")
        cprint("=" * 60, "cyan")
    else:
        cprint("\nNo URLs resolved.", "red")


if __name__ == "__main__":
    main()
