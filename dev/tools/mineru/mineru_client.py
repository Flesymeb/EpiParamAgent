from __future__ import annotations

import logging
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .config import MineruConfig, load_mineru_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MineruMarkdown:
    markdown: str
    title: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None


def pdf_file_to_markdown(
    pdf_path: Path | str,
    *,
    params: Optional[dict[str, Any]] = None,
    cfg: Optional[MineruConfig] = None,
    model_version: str = "vlm",
    poll_interval_s: float = 2.0,
    max_poll_s: int = 180,
    save_zip_to: Optional[Path | str] = None,
    data_id: Optional[str] = None,
) -> MineruMarkdown:
    """Convert a local PDF file to Markdown using MinerU v4 batch upload API.

    Steps:
    1. Request upload URL via POST /api/v4/file-urls/batch
    2. Upload file via PUT to the returned URL
    3. Poll batch result via GET /api/v4/extract-results/batch/{batch_id}
    4. Download and extract markdown from ZIP
    """
    cfg = cfg or load_mineru_config(params)
    if not cfg.base_url:
        raise RuntimeError("Missing MINERU_BASE_URL (e.g. https://mineru.net)")

    token = cfg.api_key
    base = cfg.base_url.rstrip("/")
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Step 1: Request upload URL
    batch_url = f"{base}/api/v4/file-urls/batch"
    payload = {
        "files": [{"name": pdf_path.name, "data_id": data_id or pdf_path.stem}],
        "model_version": model_version,
    }

    logger.info("Requesting upload URL for: %s", pdf_path.name)
    response = _json_post_with_retry(
        batch_url, payload, token=token, timeout_s=cfg.timeout_s
    )

    if not isinstance(response, dict) or response.get("code") != 0:
        raise RuntimeError(f"Failed to request upload URL: {_truncate_json(response)}")

    data = response.get("data", {})
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls", [])

    if not batch_id or not file_urls:
        raise RuntimeError(
            f"Invalid response from batch upload request: {_truncate_json(response)}"
        )

    upload_url = file_urls[0]
    logger.info("Got upload URL, batch_id: %s", batch_id)

    # Step 2: Upload file
    logger.info("Uploading file to MinerU...")
    with open(pdf_path, "rb") as f:
        upload_resp = _requests().put(upload_url, data=f, timeout=cfg.timeout_s)
        if upload_resp.status_code != 200:
            raise RuntimeError(f"File upload failed: status={upload_resp.status_code}")

    logger.info("File uploaded successfully. Waiting for processing...")

    # Step 3: Poll batch result
    poll_url = f"{base}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.time() + max_poll_s
    poll_count = 0

    while time.time() < deadline:
        poll_count += 1
        time.sleep(poll_interval_s)

        result = _json_get(poll_url, token=token, timeout_s=cfg.timeout_s)
        if not isinstance(result, dict) or result.get("code") != 0:
            logger.warning("Poll failed: %s", _truncate_json(result))
            continue

        data = result.get("data", {})
        extract_results = data.get("extract_result", [])

        if not extract_results:
            if poll_count % 5 == 1:
                logger.info(
                    "MinerU poll #%d: waiting for file submission...", poll_count
                )
            continue

        file_result = extract_results[0]
        state = file_result.get("state", "").lower()

        if poll_count % 5 == 1 or state in {"done", "failed"}:
            logger.info("MinerU poll #%d: state=%s", poll_count, state)

        if state == "failed":
            err_msg = file_result.get("err_msg", "Unknown error")
            raise RuntimeError(f"MinerU task failed: {err_msg}")

        if state == "done":
            zip_url = file_result.get("full_zip_url", "").strip()
            if not zip_url:
                raise RuntimeError("MinerU task done but no full_zip_url returned")

            logger.info("MinerU extraction complete. Downloading result...")
            md = _download_zip_extract_markdown(
                zip_url,
                token=token,
                timeout_s=cfg.timeout_s,
                save_to=save_zip_to,
            )
            logger.info("MinerU result extracted: %d chars", len(md))
            return MineruMarkdown(markdown=md, title=None, raw_response=result)

    raise TimeoutError(
        f"Timed out waiting for MinerU processing (batch_id: {batch_id})"
    )


def pdf_url_to_markdown(
    pdf_url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    cfg: Optional[MineruConfig] = None,
    model_version: str = "vlm",
    poll_interval_s: float = 2.0,
    max_poll_s: int = 180,
    save_zip_to: Optional[Path | str] = None,
) -> MineruMarkdown:
    """Convert a PDF (by URL) to Markdown using MinerU v4 task API.

    Based on the API pattern you shared:
    - POST /api/v4/extract/task with JSON: {"url": "https://...pdf", "model_version": "vlm"}
    - Response includes a task identifier under common keys.
    - We then poll a status/result endpoint until markdown is available.

    Notes:
    - MinerU appears to require a publicly accessible URL for the PDF.
    - Because MinerU deployments can vary, the polling is defensive and tries
      a couple of common patterns.
    """

    cfg = cfg or load_mineru_config(params)
    if not cfg.base_url:
        raise RuntimeError("Missing MINERU_BASE_URL (e.g. https://mineru.net)")

    token = cfg.api_key
    base = cfg.base_url.rstrip("/")

    task_url = base + "/" + (cfg.endpoint or "/api/v4/extract/task").lstrip("/")
    payload = {"url": pdf_url, "model_version": model_version}

    logger.info("Submitting PDF to MinerU: %s", pdf_url)
    created = _json_post(task_url, payload, token=token, timeout_s=cfg.timeout_s)

    # MinerU typically returns {"code":0, "msg":"ok", "data":{...}}
    if isinstance(created, dict):
        code = created.get("code")
        if code not in (0, "0", None):
            msg = created.get("msg") or created.get("message") or "MinerU error"
            raise RuntimeError(
                f"MinerU returned code={code}: {msg}. payload={_truncate_json(created)}"
            )

    # Some deployments might return markdown directly.
    md_direct = _find_markdown_in_json(created)
    if md_direct:
        return MineruMarkdown(
            markdown=md_direct, title=_find_title_in_json(created), raw_response=created
        )

    task_id = _find_task_id(created)
    if not task_id:
        # Give the caller the raw response for debugging.
        raise RuntimeError(
            "MinerU response did not include task_id. "
            f"payload={_truncate_json(created)}"
        )

    logger.info("MinerU task created: %s. Polling for completion...", task_id)
    deadline = time.time() + max_poll_s
    last: dict[str, Any] | None = None
    poll_count = 0

    # Try a couple of likely polling URLs. If your deployment differs, set MINERU_ENDPOINT
    # to a custom path and/or extend this mapping.
    # MinerU (mineru.net) polling works via:
    # GET /api/v4/extract/task/{task_id}
    poll_url = f"{base}/api/v4/extract/task/{task_id}"

    while time.time() < deadline:
        poll_count += 1
        last = _json_get(poll_url, token=token, timeout_s=cfg.timeout_s)
        data = (last or {}).get("data") if isinstance(last, dict) else None
        data = data if isinstance(data, dict) else {}

        state = str(data.get("state") or data.get("status") or "").lower()
        if poll_count % 5 == 1 or state in {"done", "failed", "error"}:
            logger.info("MinerU poll #%d: state=%s", poll_count, state or "unknown")

        # Some deployments may inline markdown.
        md_inline = _find_markdown_in_json(data)
        if md_inline:
            return MineruMarkdown(
                markdown=md_inline,
                title=_find_title_in_json(data),
                raw_response=last,
            )

        state = str(data.get("state") or data.get("status") or "").lower()
        if state in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(f"MinerU task failed: {_summarize_error(data)}")

        if state == "done":
            err_msg = (data.get("err_msg") or "").strip()
            if err_msg:
                raise RuntimeError(f"MinerU task done but error: {err_msg}")

            zip_url = (data.get("full_zip_url") or "").strip()
            if not zip_url:
                raise RuntimeError(
                    "MinerU task is done but no full_zip_url returned. "
                    f"Task payload keys: {sorted(data.keys())}"
                )

            logger.info(
                "MinerU extraction complete. Downloading result from: %s", zip_url[:80]
            )
            md = _download_zip_extract_markdown(
                zip_url,
                token=token,
                timeout_s=cfg.timeout_s,
                save_to=save_zip_to,
            )
            logger.info("MinerU result extracted: %d chars", len(md))
            return MineruMarkdown(markdown=md, title=None, raw_response=last)

        time.sleep(poll_interval_s)

    raise TimeoutError(
        "Timed out waiting for MinerU markdown. "
        "Check MINERU_BASE_URL/MINERU_API_KEY and the debug response JSON."
    )


def _requests():
    try:
        import requests  # type: ignore

        return requests
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "Missing dependency: requests. Install with `pip install requests`.\n"
            f"Original error: {e}"
        )


def _json_post(
    url: str,
    payload: dict[str, Any],
    *,
    token: Optional[str],
    timeout_s: int,
) -> dict[str, Any]:
    requests = _requests()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:1000]}")
    return resp.json()


def _json_get(url: str, *, token: Optional[str], timeout_s: int) -> dict[str, Any]:
    requests = _requests()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:1000]}")
    return resp.json()


def _download_zip_extract_markdown(
    zip_url: str,
    *,
    token: Optional[str],
    timeout_s: int,
    save_to: Optional[Path | str] = None,
) -> str:
    requests = _requests()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(zip_url, headers=headers, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"MinerU zip download HTTP {resp.status_code}: {resp.text[:200]}"
        )

    zbytes = resp.content

    if save_to:
        p = Path(save_to)
        p.parent.mkdir(parents=True, exist_ok=True)
        # If save_to is a directory, unzip there. If it's a file (ends in .zip), save zip.
        # But usually we want to unzip.
        # Let's assume save_to is a directory to unzip into.
        # Or if it ends in .zip, save the zip file.

        if p.suffix.lower() == ".zip":
            p.write_bytes(zbytes)
        else:
            # Unzip to directory
            with zipfile.ZipFile(BytesIO(zbytes)) as z:
                z.extractall(p)

    with zipfile.ZipFile(BytesIO(zbytes)) as z:
        names = z.namelist()
        # Prefer markdown files
        md_names = [n for n in names if n.lower().endswith((".md", ".markdown"))]
        # If no md, fall back to txt
        if not md_names:
            md_names = [n for n in names if n.lower().endswith(".txt")]
        if not md_names:
            raise RuntimeError(
                f"No markdown-like file found in MinerU zip. Entries: {names[:50]}"
            )

        # Prefer the conventional main file when present.
        lower = {n.lower(): n for n in md_names}
        for preferred in ("full.md", "full.markdown"):
            if preferred in lower:
                chosen = lower[preferred]
                break
        else:
            # Prefer root-level markdown, then shorter paths.
            md_names.sort(key=lambda n: ("/" in n, len(n)))
            chosen = md_names[0]
        data = z.read(chosen)
        try:
            return data.decode("utf-8")
        except Exception:
            return data.decode("utf-8", errors="replace")


def _find_markdown_in_json(data: Any) -> str:
    # Common patterns across deployments
    if isinstance(data, dict):
        for key in (
            "markdown",
            "md",
            "content",
            "result",
            "data",
            "output",
        ):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                md = _find_markdown_in_json(v)
                if md:
                    return md
            if isinstance(v, list):
                for item in v:
                    md = _find_markdown_in_json(item)
                    if md:
                        return md

        # Some APIs return {"code":0, "msg":"", "data":"<md>"}
        for key in ("data", "payload"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()

    if isinstance(data, list):
        for item in data:
            md = _find_markdown_in_json(item)
            if md:
                return md

    return ""


def _find_title_in_json(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        for key in ("title", "document_title", "pdf_title"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in data.values():
            t = _find_title_in_json(v)
            if t:
                return t
    if isinstance(data, list):
        for item in data:
            t = _find_title_in_json(item)
            if t:
                return t
    return None


def _find_task_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        # Common keys
        for key in ("task_id", "taskId", "id", "job_id", "jobId"):
            v = data.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()

        # Sometimes nested under data
        v = data.get("data")
        if v is not None:
            tid = _find_task_id(v)
            if tid:
                return tid

    if isinstance(data, list):
        for item in data:
            tid = _find_task_id(item)
            if tid:
                return tid
    return None


def _truncate_json(data: Any, limit: int = 800) -> str:
    try:
        import json

        s = json.dumps(data, ensure_ascii=False)
        return s[:limit] + ("..." if len(s) > limit else "")
    except Exception:
        s = str(data)
        return s[:limit] + ("..." if len(s) > limit else "")


def _is_task_failed(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    # Heuristics: status/state/code
    status = str(data.get("status") or data.get("state") or "").lower()
    if status in {"failed", "error", "canceled", "cancelled"}:
        return True
    code = data.get("code")
    try:
        if code is not None and int(code) not in (0, 200):
            return True
    except Exception:
        pass
    return False


def _summarize_error(data: Any) -> str:
    if isinstance(data, dict):
        for k in ("msg", "message", "error", "detail"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(data)[:500]


# Retry wrapper for network/API calls
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def _json_post_with_retry(
    url: str, payload: dict, *, token: str, timeout_s: int
) -> dict:
    """POST request with retry on network errors."""
    return _json_post(url, payload, token=token, timeout_s=timeout_s)
