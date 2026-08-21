"""Structured-document parser using anydoc (Rust, no ML models) — for
office formats (docx/pptx/xlsx/odt/rtf/epub/csv) and, as a fallback, PDFs
that pypdf couldn't read cleanly.

Raises ProviderError on scanned/image-only PDFs and anything else anydoc
can't extract meaningful content from, so the chain falls through to
VisionLLMParserProvider.

# ponytail: no page numbers. anydoc converts a PDF straight to Markdown
# with no page boundaries exposed, and office formats have no fixed
# pagination at all, so every block here reports page=1 and a zero bbox.
# Blocks are split on Markdown structure instead, which still gives
# per-section provenance — just not "which page". PDFs get real page
# numbers from PyPdfParserProvider, which is why that one runs first.
"""

import re

import anydoc

from app.providers.base import (
    BoundingBox,
    ExtractedBlock,
    ExtractionBlockKind,
    ParsedDocument,
    ParserProvider,
    ProviderError,
)

# Split on blank lines: Markdown's own block separator. Headings, tables
# and paragraphs all survive as distinct chunks without needing a Markdown
# parser dependency to do it.
_BLOCK_BREAK = re.compile(r"\n\s*\n+")


def _kind(text: str) -> ExtractionBlockKind:
    if text.startswith("#"):
        return ExtractionBlockKind.HEADING
    if text.startswith("|"):
        return ExtractionBlockKind.TABLE
    if re.match(r"^\s*([-*+]|\d+\.)\s", text):
        return ExtractionBlockKind.LIST_ITEM
    return ExtractionBlockKind.PARAGRAPH


class AnydocParserProvider(ParserProvider):
    name = "anydoc"

    async def parse(self, file_path: str) -> ParsedDocument:
        try:
            markdown = anydoc.to_markdown(file_path)
        except anydoc.ConvertError as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc

        blocks: list[ExtractedBlock] = []
        for index, raw in enumerate(_BLOCK_BREAK.split(markdown)):
            text = raw.strip()
            if not text:
                continue
            blocks.append(
                ExtractedBlock(
                    block_id=f"blk-{index:04d}",
                    page=1,  # no pagination available — see module note
                    kind=_kind(text),
                    text=text,
                    bbox=BoundingBox(x0=0.0, y0=0.0, x1=0.0, y1=0.0),
                    reading_order=len(blocks),
                    confidence=0.9,  # deterministic parse, but no page/bbox
                )
            )

        if not blocks:
            raise ProviderError(f"{self.name}: no content extracted from {file_path}")

        return ParsedDocument(blocks=blocks, parser_confidence=0.9, parser_name=self.name)
