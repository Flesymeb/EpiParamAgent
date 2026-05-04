from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .mineru_client import MineruMarkdown, pdf_url_to_markdown, pdf_file_to_markdown


@dataclass(frozen=True)
class PdfMarkdownExtract:
    markdown: str
    title: Optional[str]
    extracted_char_count: int
    raw_response: Optional[dict[str, Any]] = None


def extract_pdf_markdown_mineru(
    pdf_path: str | Path,
    *,
    params: Optional[dict[str, Any]] = None,
    pdf_url: Optional[str] = None,
    model_version: str = "vlm",
    output_dir: Optional[Path | str] = None,
    max_poll_s: int = 600,
) -> PdfMarkdownExtract:
    """Extract a PDF as Markdown using MinerU.

    If pdf_path is a local file, uses the batch upload API.
    If pdf_url is provided, uses the URL-based API.
    """

    path = Path(pdf_path)

    # Determine if we should use local file upload or URL mode
    if pdf_url is None and path.exists():
        # Local file mode - use batch upload API
        res: MineruMarkdown = pdf_file_to_markdown(
            pdf_path=path,
            params=params,
            model_version=model_version,
            save_zip_to=output_dir,
            data_id=path.stem,
            max_poll_s=max_poll_s,
        )
    else:
        # URL mode
        if pdf_url is None:
            if str(pdf_path).lower().startswith(("http://", "https://")):
                pdf_url = str(pdf_path)
            else:
                raise ValueError(
                    "MinerU requires either a local file or a PDF URL. "
                    "Provide `pdf_url=...` or ensure the file exists."
                )

        res: MineruMarkdown = pdf_url_to_markdown(
            pdf_url, params=params, model_version=model_version, save_zip_to=output_dir
        )

    md = (res.markdown or "").strip()
    return PdfMarkdownExtract(
        markdown=md,
        title=res.title,
        extracted_char_count=len(md),
        raw_response=res.raw_response,
    )
