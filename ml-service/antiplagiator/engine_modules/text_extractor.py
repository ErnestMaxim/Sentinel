from __future__ import annotations

import gzip
import io
import logging
import re
import tarfile
from pathlib import Path

import fitz
import requests

from engine_modules.normalizer import normalize_text_for_fingerprint
from engine_modules.constants import ARXIV_SRC_URL

LOGGER = logging.getLogger("antiplagiator.text_extractor")


class TextExtractor:
    """
    Reads a document (PDF, TeX, or plain text), optionally fetches the
    original LaTeX source from arXiv, and returns normalised word chunks.

    Parameters
    ----------
    session : requests.Session — should be the shared session from utils.build_session()
    """

    def __init__(self, session: requests.Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_and_chunk(
        self,
        file_path: Path,
        chunk_size: int = 100,
        overlap: int = 30,
        arxiv_id: str | None = None,
    ) -> tuple[list[str], str, str]: 
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_text = self._extract_raw_text(file_path, arxiv_id)
        if not raw_text:
            LOGGER.warning("Could not extract any text from %s", file_path)
            return [], "", ""

        normalized = normalize_text_for_fingerprint(raw_text)
        chunks = self._chunk_words(normalized, chunk_size, overlap, min_words=20)
        return chunks, normalized, raw_text

    # ------------------------------------------------------------------
    # LaTeX helpers
    # ------------------------------------------------------------------

    def fetch_latex_source(self, arxiv_id: str, timeout: int = 30) -> str | None:
        """
        Download and extract the primary .tex file from arXiv source tarball.
        Returns raw LaTeX string, or None on any failure.
        """
        url = ARXIV_SRC_URL.format(arxiv_id=arxiv_id)
        try:
            resp = self._session.get(url, timeout=timeout)
            if resp.status_code != 200:
                return None
            content = resp.content
        except Exception as exc:
            LOGGER.debug("LaTeX fetch failed for %s: %s", arxiv_id, exc)
            return None

        # Try tarball first, then gzip-compressed single file
        try:
            with tarfile.open(fileobj=io.BytesIO(content)) as tar:
                tex_members = [m for m in tar.getmembers() if m.name.endswith(".tex")]
                if not tex_members:
                    return None
                main_tex = max(tex_members, key=lambda m: m.size)
                f = tar.extractfile(main_tex)
                return f.read().decode("utf-8", errors="replace") if f else None
        except tarfile.TarError:
            pass

        try:
            return gzip.decompress(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    def strip_latex_structure(self, latex: str) -> str:
        """
        Remove LaTeX boilerplate (preamble, bibliography, macros) and return
        the body text with inline commands stripped.
        """
        # Strip comments
        latex = re.sub(r'%[^\n]*', ' ', latex)

        # Keep only document body
        doc_start = re.search(r'\\begin\{document\}', latex)
        if doc_start:
            latex = latex[doc_start.end():]

        # Remove bibliography
        bib = re.search(r'\\begin\{thebibliography\}', latex, re.IGNORECASE)
        if bib:
            latex = latex[:bib.start()]

        # Strip common formatting macros but keep their arguments
        for cmd in (
            "textbf", "textit", "emph", "text", "mathrm", "mathbf",
            "mathit", "mathcal", "mathbb", "mathsf", "operatorname",
            "title", "author", "section", "subsection", "subsubsection",
            "paragraph", "caption", "label", "ref", "cite",
        ):
            latex = re.sub(rf'\\{cmd}\*?\{{([^{{}}]*)\}}', r'\1', latex)

        # Remove environment markers
        latex = re.sub(r'\\(begin|end)\{[^}]*\}', ' ', latex)

        return latex

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_raw_text(self, file_path: Path, arxiv_id: str | None) -> str:
        raw_text = ""

        # 1. arXiv LaTeX source
        if arxiv_id:
            latex = self.fetch_latex_source(arxiv_id)
            if latex and len(latex.split()) >= 20:
                raw_text = self.strip_latex_structure(latex)

        # 2. Local .tex file
        if not raw_text and file_path.suffix.lower() == ".tex":
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = self.strip_latex_structure(f.read())

        # 3. PDF via PyMuPDF
        if not raw_text and file_path.suffix.lower() == ".pdf":
            raw_text = self._extract_pdf_text(file_path)

        # 4. Plain text fallback
        if not raw_text:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = re.sub(r'\s+', ' ', f.read()).strip()

        return raw_text

    def _extract_pdf_text(self, file_path: Path) -> str:
        pages_text: list[str] = []

        with fitz.open(file_path) as doc:
            for page in doc:
                page_width = page.rect.width
                blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)

                # Filter to text blocks only (block_type == 0)
                text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]

                # Detect two-column layout: if there are blocks clearly split
                # around the horizontal midpoint, sort left-col first.
                midpoint = page_width / 2
                left  = [b for b in text_blocks if b[2] <= midpoint + 20]
                right = [b for b in text_blocks if b[0] >= midpoint - 20]

                if left and right and len(right) > 1:
                    # Two-column: sort each column top-to-bottom, left before right
                    left_sorted  = sorted(left,  key=lambda b: b[1])
                    right_sorted = sorted(right, key=lambda b: b[1])
                    ordered = left_sorted + right_sorted
                else:
                    # Single column: sort top-to-bottom, left-to-right
                    ordered = sorted(text_blocks, key=lambda b: (round(b[1] / 20), b[0]))

                pages_text.append(" ".join(b[4] for b in ordered))

        raw = " ".join(pages_text)
        raw = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()

        # Strip reference section — only when it appears after 40% of the document
        # to avoid clipping the body when "References" is mentioned in the intro.
        _REF_SECTION = re.compile(
            r'(?<!\w)(References?|Bibliography|Endnotes?|Notes?|Works\s+Cited)(?!\w)',
            re.IGNORECASE,
        )
        m = _REF_SECTION.search(raw)
        if m:
            tail = raw[m.end(): m.end() + 200]
            looks_like_bib = bool(re.search(
                r'^\s*[\[\(]?\d|^\s*[A-Z][a-z]+\s+[A-Z]|doi:|http',
                tail,
            ))
            # Raised threshold: 0.20 → 0.40 to avoid clipping intro mentions
            if looks_like_bib or m.start() > len(raw) * 0.40:
                raw = raw[:m.start()]

        # Strip numbered footnote/endnote blocks
        _FOOTNOTE_BLOCK = re.compile(
            r'(?<!\d)(\d{1,3})\.\s+\S.{0,300}?(?<!\d)(\d{1,3})\.\s+\S',
            re.DOTALL,
        )
        fm = _FOOTNOTE_BLOCK.search(raw)
        if fm:
            n1, n2 = int(fm.group(1)), int(fm.group(2))
            if abs(n2 - n1) <= 2 and n1 >= 1:
                raw = raw[:fm.start()]

        return raw

    @staticmethod
    def _chunk_words(text: str, chunk_size: int, overlap: int, min_words: int) -> list[str]:
        words = text.split()
        step  = chunk_size - overlap
        return [
            " ".join(words[i: i + chunk_size])
            for i in range(0, len(words), step)
            if len(words[i: i + chunk_size]) >= min_words
        ]