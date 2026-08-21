"""Persist parsed questions and their mark-scheme entries as one linked
entity, with span-level attribution on both halves.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    ExamQuestion,
    MarkSchemeEntry,
    MarkSchemeEntrySpan,
    QuestionSpan,
    SourceSpan,
)
from app.ingestion.question_parser import (
    SpanLike,
    link_questions_to_mark_scheme,
    parse_mark_scheme,
    parse_questions,
)


@dataclass
class IngestQuestionsReport:
    """What actually landed, and what didn't. The unmatched counts are the
    parser's honesty signal — a paper whose questions mostly fail to match
    its mark scheme means the numbering conventions differ and the
    patterns in question_ref.py need tightening to the real board, not
    that the data is fine.
    """

    questions_created: int
    mark_scheme_entries_created: int
    questions_without_mark_scheme: list[str]
    mark_scheme_entries_without_question: list[str]


class QuestionIngestionService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _load_spans(self, document_id: UUID) -> list[SpanLike]:
        result = await self._session.execute(
            select(SourceSpan)
            .where(SourceSpan.document_id == document_id)
            .order_by(SourceSpan.page, SourceSpan.block_id)
        )
        return [
            SpanLike(id=s.id, page=s.page, text=s.text) for s in result.scalars().all()
        ]

    async def ingest_questions(
        self,
        *,
        paper_document_id: UUID,
        mark_scheme_document_id: UUID | None = None,
        year: int | None = None,
        paper_ref: str | None = None,
    ) -> IngestQuestionsReport:
        questions = parse_questions(await self._load_spans(paper_document_id))

        entries = (
            parse_mark_scheme(await self._load_spans(mark_scheme_document_id))
            if mark_scheme_document_id is not None
            else []
        )

        linked, orphan_entries = link_questions_to_mark_scheme(questions, entries)

        entries_created = 0
        unmatched_questions: list[str] = []

        for item in linked:
            question = ExamQuestion(
                document_id=paper_document_id,
                question_ref=item.question.number.full_ref(year=year, paper_ref=paper_ref),
                text=item.question.text,
                marks=item.question.marks,
                year=year,
                paper_ref=paper_ref,
            )
            self._session.add(question)
            await self._session.flush()  # need question.id for the links below

            for span_id in item.question.span_ids:
                self._session.add(
                    QuestionSpan(question_id=question.id, source_span_id=span_id)
                )

            if item.mark_scheme is None:
                unmatched_questions.append(item.question.number.canonical())
                continue

            entry = MarkSchemeEntry(
                question_id=question.id,
                text=item.mark_scheme.text,
                acceptable_terms=item.mark_scheme.acceptable_terms or None,
                marks_awarded=item.mark_scheme.marks_awarded,
            )
            self._session.add(entry)
            await self._session.flush()
            entries_created += 1

            for span_id in item.mark_scheme.span_ids:
                self._session.add(
                    MarkSchemeEntrySpan(
                        mark_scheme_entry_id=entry.id, source_span_id=span_id
                    )
                )

        await self._session.commit()

        return IngestQuestionsReport(
            questions_created=len(linked),
            mark_scheme_entries_created=entries_created,
            questions_without_mark_scheme=unmatched_questions,
            mark_scheme_entries_without_question=[
                e.number.canonical() for e in orphan_entries
            ],
        )
