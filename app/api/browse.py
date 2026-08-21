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
    CurriculumEdge,
    CurriculumNode,
    ExamQuestion,
    QuestionNodeMapping,
    SourceDocument,
    SourceSpan,
    TeachingUnit,
)

router = APIRouter(tags=["browse"])


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
