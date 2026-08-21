from app.emphasis.scoring import (
    EmphasisComponents,
    EmphasisWeights,
    calculate_emphasis,
    frequency_contribution,
    recency_contribution,
    recency_weight,
)


def test_frequency_contribution_uses_mapping_weight():
    assert frequency_contribution(0.7) == 0.7


def test_recency_weight_decreases_for_older_years():
    assert recency_weight(2024, 2024) == 1.0
    assert recency_weight(2020, 2024) < recency_weight(2023, 2024)


def test_recency_contribution_distributes_mapping_weight():
    assert recency_contribution(2024, 2024, 0.7) == 0.7


def test_calculate_emphasis_applies_formula_weights():
    components = EmphasisComponents(1.0, 0.5, 10.0, 0.8, 0.9)
    weights = EmphasisWeights(1.0, 2.0, 0.5, 1.0, 3.0)
    expected = 1.0 + 1.0 + 5.0 + 0.8 + 2.7
    assert calculate_emphasis(components, weights) == expected


def test_recency_weight_rejects_negative_decay():
    try:
        recency_weight(2024, 2024, -0.1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative decay should be rejected")

async def test_components_are_normalized_to_a_common_scale():
    """frequency/recency/marks are unbounded running totals while syllabus
    and structural are 0-1. Left raw, a single 10-point question makes the
    marks term dwarf the other four and the configured weights stop
    meaning anything — the "weighted formula" collapses into ranking by
    marks. Every component must land in 0-1, and so must the score.
    """
    import uuid

    from app.domain.models import CurriculumNode, ExamQuestion, MappingMethod, QuestionNodeMapping
    from app.emphasis.service import HistoricalAssessmentEmphasisService

    def node(label):
        n = CurriculumNode(
            id=uuid.uuid4(), node_type="objective", label=label,
            syllabus_ref=label, origin="machine_extracted", confidence=0.7,
        )
        return n

    big, small = node("heavily assessed"), node("barely assessed")
    rows = [
        (
            QuestionNodeMapping(question_id=uuid.uuid4(), node_id=big.id, weight=1.0,
                                confidence=1.0, mapping_method=MappingMethod.HYBRID),
            ExamQuestion(id=uuid.uuid4(), document_id=uuid.uuid4(), question_ref="q1",
                         text="t", marks=40, year=2024),
            big,
        ),
        (
            QuestionNodeMapping(question_id=uuid.uuid4(), node_id=small.id, weight=0.2,
                                confidence=0.4, mapping_method=MappingMethod.HYBRID),
            ExamQuestion(id=uuid.uuid4(), document_id=uuid.uuid4(), question_ref="q2",
                         text="t", marks=2, year=2024),
            small,
        ),
    ]

    class FakeResult:
        def all(self):
            return rows

    class FakeSession:
        async def execute(self, *_):
            return FakeResult()

    results = await HistoricalAssessmentEmphasisService(FakeSession()).calculate(current_year=2024)

    for r in results:
        for value in (r.components.frequency, r.components.recency, r.components.marks):
            assert 0.0 <= value <= 1.0, r.components
        assert 0.0 <= r.score <= 1.0

    # The heavily-assessed objective still outranks the other — normalizing
    # must preserve the ordering, not flatten it.
    assert results[0].node_id == big.id
