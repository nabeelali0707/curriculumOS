"""Layer 1 -> Layer 2 of 02_ARCHITECTURE.md: parse a source document and
persist it as source_documents + source_spans, never as flattened text.

The solver and retrieval layers only ever cite a SourceSpan, never a raw
file — this is where that provenance chain starts.
"""

import hashlib
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_provider_config
from app.domain.models import DocType, SourceDocument, SourceSpan
from app.providers.base import ParsedDocument


class _ParserRouter(Protocol):
    async def call(self, fn) -> ParsedDocument: ...


def select_parser_name() -> str:
    """Routed by document type/confidence per config/providers.yaml, but
    only docling is wired for P0 — marker/managed-OCR routing becomes real
    once those providers exist. Always returns "docling" today.
    """
    return get_provider_config()["parsing"]["born_digital_pdf"]


def hash_span_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class IngestionService:
    def __init__(self, session: AsyncSession, parser_router: _ParserRouter | None = None):
        self._session = session
        # Lazy default: importing app.providers.parsing pulls in the
        # docling SDK, which is heavy and unnecessary for callers (tests)
        # that inject their own router.
        self._parser_router = parser_router

    async def _get_router(self) -> _ParserRouter:
        if self._parser_router is not None:
            return self._parser_router
        from app.providers.parsing import get_docling_router

        return get_docling_router()

    async def ingest_document(
        self, *, file_path: str, title: str, doc_type: DocType
    ) -> SourceDocument:
        parser_name = select_parser_name()
        if parser_name != "docling":
            raise NotImplementedError(
                f"parser {parser_name!r} is configured but not wired yet — only "
                "docling is available in P0 (see app/providers/parsing/__init__.py)"
            )

        router = await self._get_router()
        parsed: ParsedDocument = await router.call(
            lambda provider: provider.parse(file_path)  # type: ignore[attr-defined]
        )

        document = SourceDocument(
            title=title,
            doc_type=doc_type,
            file_path=file_path,
            ingested_at=datetime.now(timezone.utc),
            parser_used=parsed.parser_name,
            parser_confidence=parsed.parser_confidence,
        )
        self._session.add(document)
        await self._session.flush()  # populate document.id for the spans below

        for block in parsed.blocks:
            self._session.add(
                SourceSpan(
                    document_id=document.id,
                    page=block.page,
                    block_id=block.block_id,
                    bbox=[block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1],
                    text=block.text,
                    content_hash=hash_span_text(block.text),
                )
            )

        await self._session.commit()
        await self._session.refresh(document)
        return document
