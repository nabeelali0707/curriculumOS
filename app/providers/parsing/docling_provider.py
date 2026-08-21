"""Docling parser for born-digital PDFs. Preserves page/bbox/reading-order
provenance for every block — this is the input to the provenance store
(source_documents / source_spans), so it must never flatten to plain text.

NOTE: written against Docling's documented item/provenance API as of this
writing; not yet exercised against a real PDF in this environment. Verify
the DoclingDocument shape (item.label, item.prov, iterate_items()) against
the installed docling version before trusting it in the ingestion pipeline.
"""

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DocItemLabel

from app.providers.base import (
    BoundingBox,
    ExtractedBlock,
    ExtractionBlockKind,
    ParsedDocument,
    ParserProvider,
    ProviderError,
)

_LABEL_MAP = {
    DocItemLabel.SECTION_HEADER: ExtractionBlockKind.HEADING,
    DocItemLabel.TITLE: ExtractionBlockKind.HEADING,
    DocItemLabel.TEXT: ExtractionBlockKind.PARAGRAPH,
    DocItemLabel.PARAGRAPH: ExtractionBlockKind.PARAGRAPH,
    DocItemLabel.LIST_ITEM: ExtractionBlockKind.LIST_ITEM,
    DocItemLabel.TABLE: ExtractionBlockKind.TABLE,
    DocItemLabel.PICTURE: ExtractionBlockKind.FIGURE,
}


class DoclingParserProvider(ParserProvider):
    """This class is for born-digital PDFs specifically (config/providers.yaml
    routes "scanned_or_multicolumn" elsewhere) — such a PDF already has a
    real text layer, so OCR is pure overhead: extra RapidOCR model
    downloads and CPU time for text Docling can already read directly.
    do_ocr=False turns that off. (do_table_structure stays on — the
    TableFormer model is Docling's normal layout-analysis dependency, not
    an OCR-specific extra, and disabling it would drop table structure
    from the provenance we're required to keep.)
    """

    name = "docling"

    def __init__(self):
        pipeline_options = PdfPipelineOptions(do_ocr=False)
        self._converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            },
        )

    async def parse(self, file_path: str) -> ParsedDocument:
        try:
            result = self._converter.convert(file_path)
        except Exception as exc:  # docling raises library-specific errors
            raise ProviderError(f"docling: failed to parse {file_path}: {exc}") from exc

        blocks: list[ExtractedBlock] = []
        for order, (item, _level) in enumerate(result.document.iterate_items()):
            prov = item.prov[0] if item.prov else None
            if prov is None:
                continue
            kind = _LABEL_MAP.get(item.label, ExtractionBlockKind.PARAGRAPH)
            blocks.append(
                ExtractedBlock(
                    block_id=f"blk-{order:04d}",
                    page=prov.page_no,
                    kind=kind,
                    text=getattr(item, "text", "") or "",
                    bbox=BoundingBox(
                        x0=prov.bbox.l,
                        y0=prov.bbox.t,
                        x1=prov.bbox.r,
                        y1=prov.bbox.b,
                    ),
                    reading_order=order,
                )
            )

        overall_confidence = getattr(result, "confidence", None)
        return ParsedDocument(
            blocks=blocks,
            parser_confidence=(
                overall_confidence.mean_grade
                if overall_confidence is not None
                else 1.0
            ),
            parser_name=self.name,
        )
