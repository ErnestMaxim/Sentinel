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
        with fitz.open(file_path) as doc:
            raw = " ".join(p.get_text("text") for p in doc)
        raw = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()

        # Strip trailing reference / bibliography sections.
        # The old guard (m.start() > len(raw) * 0.75) missed papers where
        # references appear in the first half or are labelled "Notes", "Endnotes",
        # etc.  We now strip unconditionally from the first occurrence of a
        # section header that consists *only* of a reference-like keyword
        # (anchored by word boundaries and surrounded by minimal context).
        _REF_SECTION = re.compile(
            r'(?<!\w)'                             # not preceded by a word char
            r'(References?|Bibliography|Endnotes?|Notes?|Works\s+Cited)'
            r'(?!\w)',                             # not followed by a word char
            re.IGNORECASE,
        )
        m = _REF_SECTION.search(raw)
        if m:
            # Only strip if the keyword is acting as a section heading:
            # must be followed by a citation-like pattern (digit, author name,
            # or bracket) within the next 200 chars, OR appear after at least
            # 20% of the document so we don't accidentally clip an abstract
            # that mentions "references to prior work".
            tail = raw[m.end(): m.end() + 200]
            looks_like_bib = bool(re.search(
                r'^\s*[\[\(]?\d|^\s*[A-Z][a-z]+\s+[A-Z]|doi:|http',
                tail,
            ))
            if looks_like_bib or m.start() > len(raw) * 0.20:
                raw = raw[:m.start()]

        # Additionally strip numbered footnote / endnote blocks anywhere in
        # the text.  These look like:
        #   "26. see note 1, fuchs 2021, at 92; ..."
        # and score 100% against the citation lists in the FAISS database.
        # We detect a run of ≥ 2 consecutive numbered items (n. <text> n+1. ...)
        # and drop everything from the first such run onward.
        _FOOTNOTE_BLOCK = re.compile(
            # Two or more consecutive numbered items: "24. ... 25. ..."
            r'(?<!\d)(\d{1,3})\.\s+\S.{0,300}?(?<!\d)(\d{1,3})\.\s+\S',
            re.DOTALL,
        )
        fm = _FOOTNOTE_BLOCK.search(raw)
        if fm:
            # Confirm the two numbers are consecutive to avoid false positives
            # on legitimate prose like "step 3. ... step 5. ..."
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