"""Extract exam questions and mark-scheme entries from already-ingested
source_spans, and link them as one entity.

Runs off spans, not the original PDF: ingestion (app/ingestion/service.py)
has already turned the document into blocks with page + bbox, so every
question this produces stays traceable to exact spans. That is the "page
attribution" 07_TASK_ROADMAP.md requires of this parser, and it's why this
step never re-reads the file.
"""

import re
from dataclasses import dataclass, field
from uuid import UUID

from app.ingestion.question_ref import (
    QuestionNumber,
    parse_question_marker,
    strip_question_marker,
)

# "[3]" or "(3 marks)" / "(1 mark)" — the per-question mark allocation.
_MARKS_BRACKET = re.compile(r"\[\s*(\d{1,2})\s*\]\s*$")
_MARKS_WORDED = re.compile(r"[\[(]\s*(\d{1,2})\s*marks?\s*[\])]", re.IGNORECASE)
# "[Total: 12]" / "(Total 12 marks)" — a section total, NOT this question's
# marks. Matched only so it can be excluded.
_MARKS_TOTAL = re.compile(r"[\[(]\s*total\b", re.IGNORECASE)

# Mark schemes separate independent marking points with ";" and
# interchangeable wordings with "/" or " OR ".
_ACCEPTABLE_SPLIT = re.compile(r"\s*/\s*|\s+OR\s+", re.IGNORECASE)


def extract_marks(text: str) -> int | None:
    """Marks allocated to a question, or None if not stated.

    A "[Total: 12]" line is deliberately not treated as a mark allocation —
    attributing a section total to one question would silently inflate that
    question's weight in the emphasis score (03_DATA_MODELS.md §4).
    """
    if not text:
        return None
    for match in _MARKS_WORDED.finditer(text):
        if not _MARKS_TOTAL.match(text[match.start() : match.end()]):
            return int(match.group(1))
    stripped = text.rstrip()
    if _MARKS_TOTAL.search(stripped):
        return None
    if (m := _MARKS_BRACKET.search(stripped)) is not None:
        return int(m.group(1))
    return None


def split_acceptable_terms(text: str) -> list[str]:
    """Interchangeable answers a mark scheme will accept, e.g.
    "glucose / sugar" -> ["glucose", "sugar"].

    Expects the entry's answer text only. Strip the question marker and
    mark annotations first (see [strip_marker_and_marks]) — these terms
    feed the mapper's terminology signal, so letting "1 (a)" or "[1]"
    through would pollute it.
    """
    if not text or not text.strip():
        return []
    terms = [t.strip(" .;,") for t in _ACCEPTABLE_SPLIT.split(text)]
    return [t for t in terms if t]


def strip_marker_and_marks(text: str, number: QuestionNumber | None = None) -> str:
    """Answer text with the leading question marker and any mark
    annotation ("[3]", "(2 marks)") removed.
    """
    body = strip_question_marker(text, number)
    body = _MARKS_WORDED.sub(" ", body)
    body = _MARKS_BRACKET.sub(" ", body.rstrip())
    return body.strip()


@dataclass
class SpanLike:
    """The subset of a SourceSpan this parser needs. Keeps parsing testable
    without a database session or ORM instances.
    """

    id: UUID
    page: int
    text: str


@dataclass
class ParsedQuestion:
    number: QuestionNumber
    text: str
    marks: int | None
    span_ids: list[UUID] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)


@dataclass
class ParsedMarkSchemeEntry:
    number: QuestionNumber
    text: str
    marks_awarded: int | None
    acceptable_terms: list[str] = field(default_factory=list)
    span_ids: list[UUID] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)


@dataclass
class LinkedQuestion:
    """A question and its mark scheme as the single entity the roadmap asks
    for. `mark_scheme` is None when no entry matched — surfaced, not
    silently dropped, because an unmatched question usually means the
    question-numbering conventions differ between the two PDFs.
    """

    question: ParsedQuestion
    mark_scheme: ParsedMarkSchemeEntry | None


def _accumulate(spans: list[SpanLike]) -> list[tuple[QuestionNumber, list[SpanLike]]]:
    """Group consecutive spans under the question marker that opened them."""
    groups: list[tuple[QuestionNumber, list[SpanLike]]] = []
    current: QuestionNumber | None = None

    for span in spans:
        marker = parse_question_marker(span.text, current)
        if marker is not None and marker != current:
            groups.append((marker, [span]))
            current = marker
        elif groups:
            groups[-1][1].append(span)
        # Spans before the first recognized marker (cover page, rubric,
        # instructions) belong to no question and are dropped here.

    return groups


def parse_questions(spans: list[SpanLike]) -> list[ParsedQuestion]:
    questions = []
    for number, group in _accumulate(spans):
        text = " ".join(s.text for s in group).strip()
        questions.append(
            ParsedQuestion(
                number=number,
                text=text,
                marks=extract_marks(text),
                span_ids=[s.id for s in group],
                pages=sorted({s.page for s in group}),
            )
        )
    return questions


def parse_mark_scheme(spans: list[SpanLike]) -> list[ParsedMarkSchemeEntry]:
    entries = []
    for number, group in _accumulate(spans):
        text = " ".join(s.text for s in group).strip()
        entries.append(
            ParsedMarkSchemeEntry(
                number=number,
                text=text,
                marks_awarded=extract_marks(text),
                acceptable_terms=split_acceptable_terms(strip_marker_and_marks(text, number)),
                span_ids=[s.id for s in group],
                pages=sorted({s.page for s in group}),
            )
        )
    return entries


def link_questions_to_mark_scheme(
    questions: list[ParsedQuestion], entries: list[ParsedMarkSchemeEntry]
) -> tuple[list[LinkedQuestion], list[ParsedMarkSchemeEntry]]:
    """Join on canonical question number.

    Returns the linked questions plus any mark-scheme entries that matched
    no question. Both halves of the mismatch are reported: an unmatched
    entry is a signal that parsing went wrong somewhere, and the roadmap
    calls this dataset differentiating enough not to shortcut.
    """
    by_number = {e.number.canonical(): e for e in entries}
    linked = [
        LinkedQuestion(question=q, mark_scheme=by_number.pop(q.number.canonical(), None))
        for q in questions
    ]
    return linked, list(by_number.values())
