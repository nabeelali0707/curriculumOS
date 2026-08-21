"""Upload -> parse -> extract endpoints. The missing glue identified during
the hackathon push: ingestion/extraction services existed but nothing
exposed them over HTTP, so a fresh DB had no way to reach a working
/planning or /generation call. Thin wrappers only — see
app/ingestion/service.py, app/ingestion/question_service.py, and
app/ingestion/curriculum_extraction.py for the actual logic.
"""

import shutil
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import DocType, SourceDocument, SourceSpan, TeachingUnit
from app.ingestion.curriculum_extraction import CurriculumExtractionError, CurriculumExtractionService
from app.ingestion.question_service import IngestQuestionsReport, QuestionIngestionService
from app.ingestion.service import IngestionService
from app.mapping.embedding_backfill import backfill_node_embeddings

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

# ponytail: local disk, not object storage — matches SourceDocument.file_path
# being a plain string path already. Upgrade path: swap for S3/GCS behind
# the same field once this leaves single-machine deployment.
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"


class DocumentOut(BaseModel):
    id: UUID
    title: str
    doc_type: str
    parser_used: str | None
    parser_confidence: float | None
    span_count: int


@router.post("/documents", response_model=DocumentOut)
async def upload_document(
    title: str = Form(...),
    doc_type: DocType = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    UPLOAD_DIR.mkdir(exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        document = await IngestionService(session).ingest_document(
            file_path=str(dest), title=title, doc_type=doc_type
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ingestion failed: {exc}") from exc

    span_count = await session.scalar(
        select(func.count()).select_from(SourceSpan).where(SourceSpan.document_id == document.id)
    )
    return DocumentOut(
        id=document.id,
        title=document.title,
        doc_type=document.doc_type.value,
        parser_used=document.parser_used,
        parser_confidence=document.parser_confidence,
        span_count=span_count or 0,
    )


class IngestQuestionsRequest(BaseModel):
    mark_scheme_document_id: UUID | None = None
    year: int | None = None
    paper_ref: str | None = None


class IngestQuestionsOut(BaseModel):
    questions_created: int
    mark_scheme_entries_created: int
    questions_without_mark_scheme: list[str]
    mark_scheme_entries_without_question: list[str]


@router.post("/documents/{document_id}/questions", response_model=IngestQuestionsOut)
async def ingest_questions(
    document_id: UUID,
    body: IngestQuestionsRequest,
    session: AsyncSession = Depends(get_session),
) -> IngestQuestionsOut:
    report: IngestQuestionsReport = await QuestionIngestionService(session).ingest_questions(
        paper_document_id=document_id,
        mark_scheme_document_id=body.mark_scheme_document_id,
        year=body.year,
        paper_ref=body.paper_ref,
    )
    return IngestQuestionsOut(**report.__dict__)


class CurriculumNodeOut(BaseModel):
    id: UUID
    node_type: str
    label: str
    syllabus_ref: str | None
    confidence: float


@router.post("/documents/{document_id}/curriculum", response_model=list[CurriculumNodeOut])
async def extract_curriculum(
    document_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[CurriculumNodeOut]:
    try:
        nodes = await CurriculumExtractionService(session).extract(document_id)
    except CurriculumExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        CurriculumNodeOut(
            id=n.id, node_type=n.node_type.value, label=n.label,
            syllabus_ref=n.syllabus_ref, confidence=n.confidence,
        )
        for n in nodes
    ]


class EmbedNodesOut(BaseModel):
    nodes_embedded: int


@router.post("/curriculum/embeddings", response_model=EmbedNodesOut)
async def embed_curriculum_nodes(session: AsyncSession = Depends(get_session)) -> EmbedNodesOut:
    """Vectorize any curriculum node that doesn't have an embedding yet.

    The mapper's shortlist only sees embedded nodes, so this has to run
    after extraction before /mappings/questions/{id} can auto-shortlist.
    """
    try:
        count = await backfill_node_embeddings(session)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"embedding provider failed: {exc}") from exc
    return EmbedNodesOut(nodes_embedded=count)


class GenerateTeachingUnitsRequest(BaseModel):
    node_ids: list[UUID]
    default_duration_minutes: int = 60
    priorities: dict[UUID, float] = {}  # optional, e.g. from /emphasis/ scores
    default_priority: float = 0.5


class TeachingUnitOut(BaseModel):
    id: UUID
    node_id: UUID
    duration_minutes: int
    priority: float


@router.post("/teaching-units", response_model=list[TeachingUnitOut])
async def generate_teaching_units(
    body: GenerateTeachingUnitsRequest, session: AsyncSession = Depends(get_session)
) -> list[TeachingUnitOut]:
    existing = (
        (
            await session.execute(
                select(TeachingUnit.node_id).where(TeachingUnit.node_id.in_(body.node_ids))
            )
        )
        .scalars()
        .all()
    )
    existing_ids = set(existing)

    created: list[TeachingUnit] = []
    for node_id in body.node_ids:
        if node_id in existing_ids:
            continue
        unit = TeachingUnit(
            node_id=node_id,
            duration_minutes=body.default_duration_minutes,
            splittable=False,
            priority=body.priorities.get(node_id, body.default_priority),
        )
        session.add(unit)
        created.append(unit)

    await session.commit()
    for unit in created:
        await session.refresh(unit)
    return [
        TeachingUnitOut(id=u.id, node_id=u.node_id, duration_minutes=u.duration_minutes, priority=u.priority)
        for u in created
    ]
