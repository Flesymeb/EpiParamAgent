from __future__ import annotations

import logging
import os
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from tools.mineru.config import MineruConfig, load_mineru_config

logger = logging.getLogger(__name__)


def _transient_request_exception_types():
    requests = _requests()
    return (
        requests.exceptions.SSLError,
        requests.exceptions.ConnectionError,
        requests.exceptions.ReadTimeout,
        requests.exceptions.Timeout,
    )


def _mineru_should_bypass_proxy(url: str, cfg: Optional[MineruConfig]) -> bool:
    if not cfg or not cfg.no_proxy:
        return False
    host = (url or '').lower()
    return any(domain in host for domain in ('mineru.net', 'openxlab.org.cn', 'cdn-mineru'))


@contextmanager
def _temporary_no_proxy(url: str, cfg: Optional[MineruConfig]):
    if not _mineru_should_bypass_proxy(url, cfg):
        yield
        return

    proxy_keys = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']
    original = {key: os.environ.get(key) for key in proxy_keys}
    no_proxy_keys = ['NO_PROXY', 'no_proxy']
    original_no_proxy = {key: os.environ.get(key) for key in no_proxy_keys}
    mineru_hosts = 'mineru.net,openxlab.org.cn,cdn-mineru.openxlab.org.cn'

    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        for key in no_proxy_keys:
            existing = original_no_proxy.get(key)
            os.environ[key] = f"{existing},{mineru_hosts}" if existing else mineru_hosts
        yield
    finally:
        for key in proxy_keys:
            if original[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original[key]
        for key in no_proxy_keys:
            if original_no_proxy[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_no_proxy[key]


def _request_with_retry(
    method: str,
    url: str,
    *,
    cfg: Optional[MineruConfig],
    timeout_s: int,
    headers: Optional[dict[str, str]] = None,
    json_payload: Optional[dict[str, Any]] = None,
    data: Any = None,
):
    requests = _requests()
    transient_types = _transient_request_exception_types()
    attempts = max(1, int(getattr(cfg, 'retry_attempts', 3) or 3))
    base_delay = float(getattr(cfg, 'retry_base_delay_s', 1.0) or 1.0)
    last_exc = None

    for attempt in range(1, attempts + 1):
        try:
            with _temporary_no_proxy(url, cfg):
                return requests.request(
                    method,
                    url,
                    headers=headers,
                    json=json_payload,
                    data=data,
                    timeout=timeout_s,
                )
        except transient_types as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                'MinerU request failed (%s %s) attempt %d/%d: %s; retrying in %.1fs',
                method,
                url[:120],
                attempt,
                attempts,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError(f'Unexpected retry loop exit for MinerU request: {method} {url}')


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
        batch_url, payload, token=token, timeout_s=cfg.timeout_s, cfg=cfg
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
        upload_resp = _request_with_retry(
            "PUT",
            upload_url,
            cfg=cfg,
            data=f,
            timeout_s=cfg.timeout_s,
        )
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

        result = _json_get(poll_url, token=token, timeout_s=cfg.timeout_s, cfg=cfg)
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
                cfg=cfg,
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
    created = _json_post(task_url, payload, token=token, timeout_s=cfg.timeout_s, cfg=cfg)

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
        last = _json_get(poll_url, token=token, timeout_s=cfg.timeout_s, cfg=cfg)
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
                cfg=cfg,
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
    cfg: Optional[MineruConfig] = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = _request_with_retry(
        "POST",
        url,
        cfg=cfg,
        headers=headers,
        json_payload=payload,
        timeout_s=timeout_s,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:1000]}")
    return resp.json()


def _json_get(
    url: str,
    *,
    token: Optional[str],
    timeout_s: int,
    cfg: Optional[MineruConfig] = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = _request_with_retry(
        "GET",
        url,
        cfg=cfg,
        headers=headers,
        timeout_s=timeout_s,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:1000]}")
    return resp.json()


def _download_zip_extract_markdown(
    zip_url: str,
    *,
    token: Optional[str],
    timeout_s: int,
    save_to: Optional[Path | str] = None,
    cfg: Optional[MineruConfig] = None,
) -> str:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = _request_with_retry(
        "GET",
        zip_url,
        cfg=cfg,
        headers=headers,
        timeout_s=timeout_s,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"MinerU zip download HTTP {resp.status_code}: {resp.text[:200]}"
        )

    zbytes = resp.content

    if save_to:
        p = Path(save_to)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() == ".zip":
            p.write_bytes(zbytes)
        else:
            with zipfile.ZipFile(BytesIO(zbytes)) as z:
                z.extractall(p)

    with zipfile.ZipFile(BytesIO(zbytes)) as z:
        names = z.namelist()
        md_names = [n for n in names if n.lower().endswith((".md", ".markdown"))]
        if not md_names:
            md_names = [n for n in names if n.lower().endswith(".txt")]
        if not md_names:
            raise RuntimeError(
                f"No markdown-like file found in MinerU zip. Entries: {names[:50]}"
            )

        lower = {n.lower(): n for n in md_names}
        for preferred in ("full.md", "full.markdown"):
            if preferred in lower:
                chosen = lower[preferred]
                break
        else:
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
def _json_post_with_retry(
    url: str,
    payload: dict,
    *,
    token: str,
    timeout_s: int,
    cfg: Optional[MineruConfig] = None,
) -> dict:
    """POST request with retry on transient MinerU network errors."""
    return _json_post(url, payload, token=token, timeout_s=timeout_s, cfg=cfg)
