"""Read-only listing endpoints for the teacher workspace UI. Nothing here
computes anything new — every value is a direct read of tables that other
routers already write to. Split out from those routers because they're
GETs with no business logic, not because the resources are unrelated.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import (
    Claim,
    ClaimEvidence,
    CurriculumEdge,
    CurriculumNode,
    ExamQuestion,
    NodeType,
    QuestionNodeMapping,
    ScheduledUnit,
    SourceDocument,
    SourceSpan,
    TeachingUnit,
)

router = APIRouter(tags=["browse"])


class StatsOut(BaseModel):
    documents: int
    spans: int
    objectives: int
    questions: int
    mappings: int
    units: int
    scheduled: int
    claims: int


@router.get("/stats", response_model=StatsOut)
async def stats(session: AsyncSession = Depends(get_session)) -> StatsOut:
    """The eight quantities that flow through the pipeline, in one request.

    The workspace shows these as a single row so a stalled stage reads as a
    zero next to a populated neighbour. Assembling them client-side meant a
    request per question just to total the mappings; this is one round trip
    that stays flat as the corpus grows.
    """

    async def count(model, *where):
        return await session.scalar(select(func.count()).select_from(model).where(*where)) or 0

    # Max rather than sum: scheduled_units holds every plan version, and
    # the figure that means something is the size of one plan, not the
    # total across every replan ever solved.
    per_plan = (
        select(func.count().label("n"))
        .select_from(ScheduledUnit)
        .group_by(ScheduledUnit.plan_version)
        .subquery()
    )
    scheduled = await session.scalar(select(func.max(per_plan.c.n)))

    return StatsOut(
        documents=await count(SourceDocument),
        spans=await count(SourceSpan),
        objectives=await count(CurriculumNode, CurriculumNode.node_type == NodeType.OBJECTIVE),
        questions=await count(ExamQuestion),
        mappings=await count(QuestionNodeMapping),
        units=await count(TeachingUnit),
        scheduled=scheduled or 0,
        claims=await count(Claim),
    )


class DocumentOut(BaseModel):
    id: UUID
    title: str
    doc_type: str
    parser_used: str | None
    span_count: int


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(session: AsyncSession = Depends(get_session)) -> list[DocumentOut]:
    docs = (await session.execute(select(SourceDocument))).scalars().all()
    out = []
    for d in docs:
        count = await session.scalar(
            select(func.count()).select_from(SourceSpan).where(SourceSpan.document_id == d.id)
        )
        out.append(
            DocumentOut(id=d.id, title=d.title, doc_type=d.doc_type.value, parser_used=d.parser_used, span_count=count or 0)
        )
    return out


class CurriculumNodeOut(BaseModel):
    id: UUID
    node_type: str
    label: str
    syllabus_ref: str | None
    origin: str
    confidence: float


@router.get("/curriculum-nodes", response_model=list[CurriculumNodeOut])
async def list_curriculum_nodes(session: AsyncSession = Depends(get_session)) -> list[CurriculumNodeOut]:
    nodes = (await session.execute(select(CurriculumNode))).scalars().all()
    return [
        CurriculumNodeOut(
            id=n.id, node_type=n.node_type.value, label=n.label,
            syllabus_ref=n.syllabus_ref, origin=n.origin.value, confidence=n.confidence,
        )
        for n in nodes
    ]


class CurriculumEdgeOut(BaseModel):
    id: UUID
    source_node_id: UUID
    target_node_id: UUID
    edge_type: str


@router.get("/curriculum-edges", response_model=list[CurriculumEdgeOut])
async def list_curriculum_edges(session: AsyncSession = Depends(get_session)) -> list[CurriculumEdgeOut]:
    edges = (await session.execute(select(CurriculumEdge))).scalars().all()
    return [
        CurriculumEdgeOut(id=e.id, source_node_id=e.source_node_id, target_node_id=e.target_node_id, edge_type=e.edge_type.value)
        for e in edges
    ]


class QuestionOut(BaseModel):
    id: UUID
    question_ref: str
    text: str
    marks: int | None


@router.get("/questions", response_model=list[QuestionOut])
async def list_questions(session: AsyncSession = Depends(get_session)) -> list[QuestionOut]:
    questions = (await session.execute(select(ExamQuestion))).scalars().all()
    return [QuestionOut(id=q.id, question_ref=q.question_ref, text=q.text[:280], marks=q.marks) for q in questions]


class MappingOut(BaseModel):
    id: UUID
    node_id: UUID
    node_label: str
    weight: float
    confidence: float
    mapping_method: str


@router.get("/questions/{question_id}/mappings", response_model=list[MappingOut])
async def list_question_mappings(
    question_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[MappingOut]:
    rows = (
        await session.execute(
            select(QuestionNodeMapping, CurriculumNode)
            .join(CurriculumNode, CurriculumNode.id == QuestionNodeMapping.node_id)
            .where(QuestionNodeMapping.question_id == question_id)
        )
    ).all()
    return [
        MappingOut(
            id=m.id, node_id=m.node_id, node_label=n.label,
            weight=m.weight, confidence=m.confidence, mapping_method=m.mapping_method.value,
        )
        for m, n in rows
    ]


class CitationOut(BaseModel):
    document_title: str
    page: int
    excerpt: str


class ClaimOut(BaseModel):
    id: UUID
    text: str
    verification_status: str
    confidence: float
    generation_model: str
    verification_model: str
    citations: list[CitationOut]


@router.get("/claims", response_model=list[ClaimOut])
async def list_claims(session: AsyncSession = Depends(get_session)) -> list[ClaimOut]:
    """Generated claims with their evidence resolved to document + page.

    Generation is the slowest, most rate-limited step in the pipeline, so
    its output has to survive a page reload — re-running it just to look at
    what it already produced is exactly what a metered demo can't afford.
    Resolving the citations here is also the honest way to show the
    provenance chain: these page numbers come from a join, not from the
    model's own say-so.
    """
    claims = (
        (await session.execute(select(Claim).order_by(Claim.created_at.desc()))).scalars().all()
    )
    if not claims:
        return []

    rows = (
        await session.execute(
            select(ClaimEvidence.claim_id, SourceDocument.title, SourceSpan.page, SourceSpan.text)
            .join(SourceSpan, SourceSpan.id == ClaimEvidence.source_span_id)
            .join(SourceDocument, SourceDocument.id == SourceSpan.document_id)
            .where(ClaimEvidence.claim_id.in_([c.id for c in claims]))
        )
    ).all()

    by_claim: dict[UUID, list[CitationOut]] = {}
    for claim_id, title, page, text in rows:
        by_claim.setdefault(claim_id, []).append(
            CitationOut(document_title=title, page=page, excerpt=" ".join(text.split())[:200])
        )

    return [
        ClaimOut(
            id=c.id, text=c.text, verification_status=c.verification_status.value,
            confidence=c.confidence, generation_model=c.generation_model,
            verification_model=c.verification_model, citations=by_claim.get(c.id, []),
        )
        for c in claims
    ]


class TeachingUnitOut(BaseModel):
    id: UUID
    node_id: UUID
    node_label: str
    duration_minutes: int
    priority: float


@router.get("/teaching-units", response_model=list[TeachingUnitOut])
async def list_teaching_units(session: AsyncSession = Depends(get_session)) -> list[TeachingUnitOut]:
    rows = (
        await session.execute(select(TeachingUnit, CurriculumNode).join(CurriculumNode, CurriculumNode.id == TeachingUnit.node_id))
    ).all()
    return [
        TeachingUnitOut(id=u.id, node_id=u.node_id, node_label=n.label, duration_minutes=u.duration_minutes, priority=u.priority)
        for u, n in rows
    ]
