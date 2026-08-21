"""Text-layer PDF parser using pypdf — no ML models, no download, and the
only parser in the chain that yields real page numbers.

anydoc produces better-structured Markdown, but for PDFs it emits one flat
string with no page boundaries at all, which can't satisfy the provenance
requirement ("this span is on page 47"). So PDFs come through here first
and fall back to anydoc only if there's no text layer to read.

# ponytail: paragraph granularity via blank-line splitting, with the bbox
# still the full page rect rather than the paragraph's true rectangle —
# pypdf's extract_text() doesn't expose per-run coordinates. Page
# attribution is therefore exact; sub-page bbox is not. Upgrade path:
# DoclingParserProvider, whose layout model gives true paragraph boxes,
# once that download is acceptable.
"""

import re

from pypdf import PdfReader

from app.providers.base import (
    BoundingBox,
    ExtractedBlock,
    ExtractionBlockKind,
    ParsedDocument,
    ParserProvider,
    ProviderError,
)

# Two-or-more newlines: a paragraph break in extracted PDF text. Single
# newlines are line wraps inside one paragraph and must not split a block.
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")

# Not every PDF puts blank lines between paragraphs — plenty of generated
# ones emit a whole page as a single run of single-newline lines. Without a
# ceiling those become one span per page, which is too coarse to cite or to
# retrieve against, so anything longer gets split again on line boundaries.
_MAX_BLOCK_CHARS = 900


def _split_page(page_text: str) -> list[str]:
    chunks: list[str] = []
    for raw in _PARAGRAPH_BREAK.split(page_text):
        para = raw.strip()
        if not para:
            continue
        if len(para) <= _MAX_BLOCK_CHARS:
            chunks.append(para)
            continue
        current: list[str] = []
        size = 0
        for line in para.split("\n"):
            if size + len(line) > _MAX_BLOCK_CHARS and current:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        if current:
            chunks.append("\n".join(current))
    return chunks

# A heading is short, has no sentence-ending punctuation, and isn't a
# fragment of prose. Crude, but it's the difference between a block tagged
# HEADING and one tagged PARAGRAPH, not a correctness boundary.
_MAX_HEADING_CHARS = 80


def _kind(text: str) -> ExtractionBlockKind:
    if len(text) <= _MAX_HEADING_CHARS and "\n" not in text and not text.endswith((".", ",", ";")):
        return ExtractionBlockKind.HEADING
    return ExtractionBlockKind.PARAGRAPH


class PyPdfParserProvider(ParserProvider):
    name = "pypdf_text"

    async def parse(self, file_path: str) -> ParsedDocument:
        try:
            reader = PdfReader(file_path)
        except Exception as exc:  # pypdf raises library-specific errors
            raise ProviderError(f"{self.name}: failed to open {file_path}: {exc}") from exc

        blocks: list[ExtractedBlock] = []
        reading_order = 0
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:
                raise ProviderError(f"{self.name}: page {page_number}: {exc}") from exc

            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            for para_index, text in enumerate(_split_page(page_text)):
                blocks.append(
                    ExtractedBlock(
                        block_id=f"p{page_number:04d}-b{para_index:03d}",
                        page=page_number,
                        kind=_kind(text),
                        text=text,
                        bbox=BoundingBox(x0=0.0, y0=0.0, x1=width, y1=height),
                        reading_order=reading_order,
                        confidence=0.8,  # exact page, approximate bbox — see module note
                    )
                )
                reading_order += 1

        if not blocks:
            # A scanned PDF extracts to nothing here. Raising (rather than
            # returning an empty document) is what lets the parser chain
            # fall through to the OCR provider — a silently-empty success
            # would look like a completed upload with no content.
            raise ProviderError(
                f"{self.name}: no extractable text in {file_path} (scanned PDF?)"
            )

        return ParsedDocument(blocks=blocks, parser_confidence=0.8, parser_name=self.name)
