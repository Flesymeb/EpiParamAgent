from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PdfExtract:
    text: str
    title: str | None
    page_count: int
    extracted_char_count: int
    likely_scanned: bool


def extract_pdf_text(
    pdf_path: str | Path, *, max_pages: int | None = None
) -> PdfExtract:
    """Extract text from a PDF.

    Uses PyMuPDF (pymupdf). This extracts the *text layer*.
    If the PDF is scanned (image-only), extracted text may be empty.
    """

    path = Path(pdf_path)
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "Missing dependency: pymupdf. Install with `pip install pymupdf`.\n"
            f"Original error: {e}"
        )

    doc = fitz.open(path)
    try:
        title = None
        try:
            md = doc.metadata or {}
            title = (md.get("title") or "").strip() or None
        except Exception:
            title = None

        n_pages = doc.page_count
        limit = min(n_pages, max_pages) if max_pages else n_pages

        parts: list[str] = []
        total_chars = 0
        for i in range(limit):
            page = doc.load_page(i)
            t = page.get_text("text") or ""
            t = t.strip()
            if t:
                parts.append(f"\n\n[PAGE {i+1}]\n" + t)
                total_chars += len(t)

        text = "".join(parts).strip()

        # Heuristic: if almost no text extracted, it is likely scanned.
        likely_scanned = total_chars < 200

        return PdfExtract(
            text=text,
            title=title,
            page_count=n_pages,
            extracted_char_count=total_chars,
            likely_scanned=likely_scanned,
        )
    finally:
        doc.close()


def extract_pdf_images(
    pdf_path: str | Path,
    *,
    out_dir: str | Path,
    max_pages: int | None = None,
) -> list[Path]:
    """Extract embedded images from a PDF.

    This does NOT interpret charts/tables; it just saves images so you can inspect
    or run OCR/vision later.
    """

    path = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "Missing dependency: pymupdf. Install with `pip install pymupdf`.\n"
            f"Original error: {e}"
        )

    doc = fitz.open(path)
    images: list[Path] = []
    try:
        n_pages = doc.page_count
        limit = min(n_pages, max_pages) if max_pages else n_pages

        for page_index in range(limit):
            page = doc.load_page(page_index)
            for img_index, info in enumerate(page.get_images(full=True)):
                xref = info[0]
                img = doc.extract_image(xref)
                ext = (img.get("ext") or "png").lower()
                data = img.get("image")
                if not data:
                    continue

                out_path = out / f"{path.stem}_p{page_index+1}_img{img_index+1}.{ext}"
                out_path.write_bytes(data)
                images.append(out_path)

        return images
    finally:
        doc.close()
