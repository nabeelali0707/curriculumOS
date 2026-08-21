from app.providers.parsing.docling_provider import DoclingParserProvider
from app.providers.router import ProviderRouter

# Routing by document type/confidence (born_digital_pdf -> docling,
# scanned_or_multicolumn -> marker) is ingestion-pipeline logic, not a
# single default provider — app/ingestion/ picks the provider per document
# rather than this module exposing one get_*_router() like llm/embeddings
# do. Only Docling is wired for P0; Marker and a managed-OCR fallback are
# deferred until the ingestion evaluation in weeks 1-2 shows they're needed.


def get_docling_router() -> ProviderRouter:
    return ProviderRouter(DoclingParserProvider())
