import uuid

import pytest

from app.ingestion.question_parser import (
    SpanLike,
    extract_marks,
    link_questions_to_mark_scheme,
    parse_mark_scheme,
    parse_questions,
    split_acceptable_terms,
    strip_marker_and_marks,
)
from app.ingestion.question_ref import QuestionNumber


def _span(text: str, page: int = 1) -> SpanLike:
    return SpanLike(id=uuid.uuid4(), page=page, text=text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Explain how enzymes work. [3]", 3),
        ("Describe the process (4 marks)", 4),
        ("State one reason (1 mark)", 1),
        ("Explain why this happens.", None),
        ("", None),
    ],
)
def test_extract_marks(text, expected):
    assert extract_marks(text) == expected


def test_section_total_is_not_treated_as_question_marks():
    # Attributing a section total to one question would inflate that
    # question's weight in the emphasis score.
    assert extract_marks("[Total: 12]") is None
    assert extract_marks("End of section (Total 40 marks)") is None


def test_split_acceptable_terms():
    assert split_acceptable_terms("glucose / sugar") == ["glucose", "sugar"]
    assert split_acceptable_terms("diffusion OR passive transport") == [
        "diffusion",
        "passive transport",
    ]
    assert split_acceptable_terms("") == []


def test_strip_marker_and_marks_leaves_only_answer_text():
    assert strip_marker_and_marks("1 (a) osmosis / diffusion [1]") == "osmosis / diffusion"
    assert strip_marker_and_marks("2(b) water moves down (3 marks)") == "water moves down"
    assert strip_marker_and_marks("no marker here") == "no marker here"


def test_parse_questions_groups_continuation_spans():
    spans = [
        _span("Answer all questions.", page=1),  # rubric, before any marker
        _span("1 The diagram shows a cell.", page=2),
        _span("(a) Name structure X. [1]", page=2),
        _span("(b) Explain its function. [3]", page=3),
        _span("2 Enzymes are proteins.", page=3),
    ]

    questions = parse_questions(spans)

    assert [q.number for q in questions] == [
        QuestionNumber(1, None, None),
        QuestionNumber(1, "a", None),
        QuestionNumber(1, "b", None),
        QuestionNumber(2, None, None),
    ]
    assert questions[1].marks == 1
    assert questions[2].marks == 3


def test_parsed_question_carries_span_and_page_attribution():
    stem = _span("3 A plant is kept in the dark.", page=4)
    body = _span("It is then exposed to light for six hours. [2]", page=5)

    questions = parse_questions([stem, body])

    assert len(questions) == 1
    question = questions[0]
    # Every span the question was built from is retained, so the question
    # stays traceable back to exact blocks — not just a page number.
    assert question.span_ids == [stem.id, body.id]
    assert question.pages == [4, 5]
    assert question.text.startswith("3 A plant is kept in the dark.")


def test_spans_before_first_marker_are_not_attributed_to_a_question():
    questions = parse_questions([_span("Instructions to candidates"), _span("Time: 1h 45m")])
    assert questions == []


def test_link_questions_to_mark_scheme_joins_on_canonical_number():
    paper = [_span("1(a) Name the process. [1]"), _span("1(b) Explain why. [3]")]
    # Mark scheme writes the same questions with different spacing.
    scheme = [_span("1 (a) osmosis / diffusion [1]"), _span("1 (b) water moves down [3]")]

    linked, orphans = link_questions_to_mark_scheme(
        parse_questions(paper), parse_mark_scheme(scheme)
    )

    assert orphans == []
    assert len(linked) == 2
    assert all(item.mark_scheme is not None for item in linked)
    # The question marker and mark bracket are structural, not answers —
    # they must not leak into the terms that feed the mapper.
    assert linked[0].mark_scheme.acceptable_terms == ["osmosis", "diffusion"]
    assert linked[0].mark_scheme.marks_awarded == 1


def test_unmatched_questions_and_entries_are_reported_not_dropped():
    linked, orphans = link_questions_to_mark_scheme(
        parse_questions([_span("1(a) Name the process. [1]")]),
        parse_mark_scheme([_span("2(a) unrelated entry [2]")]),
    )

    assert len(linked) == 1
    assert linked[0].mark_scheme is None  # question kept, mismatch visible
    assert [e.number.canonical() for e in orphans] == ["q2a"]
