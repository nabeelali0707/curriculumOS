import uuid

import pytest

from app.domain.models import DocType, SourceDocument, SourceSpan
from app.ingestion.service import IngestionService, hash_span_text
from app.providers.base import (
    BoundingBox,
    ExtractedBlock,
    ExtractionBlockKind,
    ParsedDocument,
    ProviderError,
)


class FakeSession:
    """Stands in for AsyncSession: no real DB, just tracks what would have
    been persisted and mimics the one ORM behavior the service relies on
    (flush() populating the primary key)."""

    def __init__(self):
        self.added: list[object] = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, SourceDocument) and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass


class FakeParserProvider:
    def __init__(self, parsed: ParsedDocument):
        self._parsed = parsed

    async def parse(self, file_path: str) -> ParsedDocument:
        return self._parsed


class FakeParserRouter:
    def __init__(self, parsed: ParsedDocument):
        self._provider = FakeParserProvider(parsed)

    async def call(self, fn):
        return await fn(self._provider)


def _sample_parsed_document() -> ParsedDocument:
    return ParsedDocument(
        parser_name="docling",
        parser_confidence=0.91,
        blocks=[
            ExtractedBlock(
                block_id="blk-0000",
                page=47,
                kind=ExtractionBlockKind.PARAGRAPH,
                text="Mitosis produces two genetically identical daughter cells.",
                bbox=BoundingBox(x0=102, y0=340, x1=480, y1=402),
                reading_order=0,
            ),
            ExtractedBlock(
                block_id="blk-0001",
                page=47,
                kind=ExtractionBlockKind.HEADING,
                text="Cell Division",
                bbox=BoundingBox(x0=100, y0=300, x1=400, y1=330),
                reading_order=1,
            ),
        ],
    )


async def test_ingest_document_persists_document_and_spans():
    session = FakeSession()
    service = IngestionService(session, parser_router=FakeParserRouter(_sample_parsed_document()))

    document = await service.ingest_document(
        file_path="bio-textbook-v3.pdf", title="Biology Textbook v3", doc_type=DocType.TEXTBOOK
    )

    assert session.committed
    assert document.id is not None
    assert document.parser_used == "docling"
    assert document.parser_confidence == 0.91

    spans = [obj for obj in session.added if isinstance(obj, SourceSpan)]
    assert len(spans) == 2

    first = spans[0]
    assert first.document_id == document.id
    assert first.page == 47
    assert first.block_id == "blk-0000"
    assert first.bbox == [102, 340, 480, 402]
    assert first.text == "Mitosis produces two genetically identical daughter cells."
    assert first.content_hash == hash_span_text(first.text)
    assert first.content_hash.startswith("sha256:")


async def test_ingest_document_propagates_parser_failure():
    """A parser that can't read the file must surface as an error, not as a
    silently-empty document — an ingested-but-blank source would look like a
    successful upload while breaking every downstream citation.
    """

    class FailingRouter:
        async def call(self, fn):
            raise ProviderError("no parser could read this file")

    service = IngestionService(FakeSession(), parser_router=FailingRouter())

    with pytest.raises(ProviderError):
        await service.ingest_document(
            file_path="scanned.pdf", title="Scanned Doc", doc_type=DocType.TEXTBOOK
        )


def test_parser_chain_puts_page_attribution_first_and_ocr_last():
    """Order is load-bearing, not cosmetic: pypdf_text is the only parser
    that reports real page numbers (the product's provenance requirement),
    OCR is the slow token-costing last resort, and docling must never be
    reachable from the default chain because its layout model downloads on
    first use. See app/providers/parsing/__init__.py.
    """
    from app.config import get_provider_config

    priority = get_provider_config()["parsing"]["priority"]
    assert priority[0] == "pypdf_text"
    assert priority[-1] == "vision_llm_ocr"
    assert "docling" not in priority


def test_hash_span_text_is_deterministic_and_sensitive_to_content():
    a = hash_span_text("Mitosis produces two genetically identical daughter cells.")
    b = hash_span_text("Mitosis produces two genetically identical daughter cells.")
    c = hash_span_text("Meiosis produces four genetically distinct cells.")
    assert a == b
    assert a != c
