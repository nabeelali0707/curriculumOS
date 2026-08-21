import pytest

from app.ingestion.question_ref import QuestionNumber, parse_question_marker


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1(a)(ii) Explain how...", QuestionNumber(1, "a", "ii")),
        ("1 (a) (ii)  Explain", QuestionNumber(1, "a", "ii")),
        ("2(b) Describe", QuestionNumber(2, "b", None)),
        ("Q1(a) State", QuestionNumber(1, "a", None)),
        ("Question 3 (c) Give", QuestionNumber(3, "c", None)),
        ("5b Calculate", QuestionNumber(5, "b", None)),
        ("12(d)(iv) Suggest", QuestionNumber(12, "d", "iv")),
        ("1.1 What is", QuestionNumber(1, "1", None)),
        ("7 The diagram shows", QuestionNumber(7, None, None)),
        ("4. Define", QuestionNumber(4, None, None)),
    ],
)
def test_parses_common_conventions(text, expected):
    assert parse_question_marker(text) == expected


def test_bare_number_not_confused_by_following_word():
    # "1 a diagram..." must not read 'a' as part (a) — the adjacent-letter
    # form requires no space, so this stays question 1 with no part.
    assert parse_question_marker("1 a diagram shows a cell") == QuestionNumber(1, None, None)


def test_continuation_part_inherits_current_number():
    current = QuestionNumber(3, "a", None)
    assert parse_question_marker("(b) Explain why", current) == QuestionNumber(3, "b", None)


def test_continuation_subpart_inherits_number_and_part():
    current = QuestionNumber(3, "b", None)
    assert parse_question_marker("(ii) Give one reason", current) == QuestionNumber(3, "b", "ii")


def test_continuation_without_context_is_unresolvable():
    # "(b)" with no question in scope cannot be resolved to a number, and
    # must not guess one.
    assert parse_question_marker("(b) Explain why") is None


def test_roman_vs_letter_ambiguity_resolved_by_context():
    # "(i)" is sub-part i when a part is in scope...
    assert parse_question_marker("(i) State", QuestionNumber(2, "a", None)) == QuestionNumber(
        2, "a", "i"
    )
    # ...but part i when only a number is in scope.
    assert parse_question_marker("(i) State", QuestionNumber(2, None, None)) == QuestionNumber(
        2, "i", None
    )


def test_prose_is_not_a_question_marker():
    assert parse_question_marker("The diagram shows a plant cell.") is None
    assert parse_question_marker("") is None


def test_canonical_forms():
    assert QuestionNumber(5, "b").canonical() == "q5b"
    assert QuestionNumber(5, "b", "ii").canonical() == "q5bii"
    assert QuestionNumber(5).canonical() == "q5"
    # Numeric AQA-style part keeps a separator so q1.1 can't collide with q11.
    assert QuestionNumber(1, "1").canonical() == "q1.1"
    assert QuestionNumber(1, "1").canonical() != QuestionNumber(11).canonical()


def test_full_ref_matches_data_model_example():
    # 03_DATA_MODELS.md uses "2024_p2_q5b" as the question_ref example.
    assert QuestionNumber(5, "b").full_ref(year=2024, paper_ref="p2") == "2024_p2_q5b"


def test_full_ref_omits_unknown_pieces():
    assert QuestionNumber(5, "b").full_ref(year=None, paper_ref=None) == "q5b"
    assert QuestionNumber(5, "b").full_ref(year=2024, paper_ref=None) == "2024_q5b"
