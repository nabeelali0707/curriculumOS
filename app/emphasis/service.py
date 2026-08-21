"""Database orchestration for historical assessment emphasis scores."""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CurriculumNode, ExamQuestion, QuestionNodeMapping
from app.emphasis.scoring import (
    EmphasisComponents,
    EmphasisWeights,
    frequency_contribution,
    historical_assessment_emphasis_score,
    recency_contribution,
)


@dataclass(frozen=True)
class HistoricalAssessmentEmphasisResult:
    """A score plus its inputs, so prioritization remains inspectable by teachers."""

    node_id: UUID
    score: float
    components: EmphasisComponents


class HistoricalAssessmentEmphasisService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def calculate(
        self,
        *,
        current_year: int | None = None,
        decay: float = 0.2,
        weights: EmphasisWeights | None = None,
    ) -> list[HistoricalAssessmentEmphasisResult]:
        """Aggregate mapped questions while keeping syllabus relevance in every result."""
        rows = (
            await self._session.execute(
                select(QuestionNodeMapping, ExamQuestion, CurriculumNode)
                .join(ExamQuestion, ExamQuestion.id == QuestionNodeMapping.question_id)
                .join(CurriculumNode, CurriculumNode.id == QuestionNodeMapping.node_id)
            )
        ).all()

        years = [question.year for _, question, _ in rows if question.year is not None]
        reference_year = current_year if current_year is not None else max(years, default=0)

        frequency: dict[UUID, float] = defaultdict(float)
        recency: dict[UUID, float] = defaultdict(float)
        marks: dict[UUID, float] = defaultdict(float)
        nodes: dict[UUID, CurriculumNode] = {}

        for mapping, question, node in rows:
            contribution = frequency_contribution(mapping.weight)
            frequency[node.id] += contribution
            marks[node.id] += contribution * max(question.marks or 0, 0)
            if question.year is not None:
                recency[node.id] += recency_contribution(
                    question.year, reference_year, mapping.weight, decay
                )
            nodes[node.id] = node

        # Frequency, recency and marks are unbounded running totals —
        # frequency counts mapping weights, marks multiplies those by raw
        # point values. Syllabus and structural are already 0-1. Combining
        # them raw makes the configured weights meaningless: one 10-point
        # question contributes a marks term an order of magnitude larger
        # than the other four signals combined, so the "weighted formula"
        # 03_DATA_MODELS.md §4 asks for silently degenerates into ranking
        # by marks alone. Scaling each to its own maximum puts all five on
        # a common 0-1 scale, which is what makes the weights express
        # relative importance and the score comparable between objectives.
        scale = {
            "frequency": max(frequency.values(), default=0.0),
            "recency": max(recency.values(), default=0.0),
            "marks": max(marks.values(), default=0.0),
        }

        def _normalized(totals: dict[UUID, float], key: str, node_id: UUID) -> float:
            largest = scale[key]
            return totals[node_id] / largest if largest > 0 else 0.0

        results = []
        for node_id, node in nodes.items():
            # The schema has no separate W/S values: syllabus_ref is the
            # available current-spec membership signal, and confidence is the
            # available structural-match confidence. Replace these proxies
            # when explicit syllabus weighting/specification data is modelled.
            components = EmphasisComponents(
                frequency=_normalized(frequency, "frequency", node_id),
                recency=_normalized(recency, "recency", node_id),
                marks=_normalized(marks, "marks", node_id),
                syllabus=1.0 if node.syllabus_ref else 0.0,
                structural=max(0.0, min(1.0, node.confidence)),
            )
            results.append(
                HistoricalAssessmentEmphasisResult(
                    node_id=node_id,
                    score=historical_assessment_emphasis_score(components, weights),
                    components=components,
                )
            )

        return sorted(results, key=lambda result: result.score, reverse=True)