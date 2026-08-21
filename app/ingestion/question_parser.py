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

# "[3]" or "(3 marks)" / "(1 mark)" / "[10 points]" — the per-question
# allocation. "points" is as common as "marks" in practice, and papers
# routinely itemize the split before the total: "[5+5=10 points]". Anchor
# on the number immediately preceding the word, which is the total in that
# form, rather than requiring the number to open the bracket — otherwise
# every itemized question silently records no marks at all, and marks are
# a weighted term in the emphasis score (03_DATA_MODELS.md §4).
_MARKS_BRACKET = re.compile(r"\[\s*(\d{1,2})\s*\]\s*$")
_MARKS_WORDED = re.compile(
    r"[\[(][^\])]*?(\d{1,3})\s*(?:marks?|points?)\s*[\])]", re.IGNORECASE
)
# "[Total: 12]" / "(Total 12 marks)" — a section total, NOT this question's
# marks. Matched only so it can be excluded.
_MARKS_TOTAL = re.compile(r"[\[(]\s*total\b", re.IGNORECASE)

# Mark schemes separate independent marking points with ";" and
# interchangeable wordings with "/" or " OR ".
_ACCEPTABLE_SPLIT = re.compile(r"\s*/\s*|\s+OR\s+", re.IGNORECASE)

# A question heading doesn't always start its block. Real papers routinely
# run a learning-outcome preamble straight into the question:
# "...common algorithmic operations (10 points] Question 3: You are
# required to..." — leaving that unsplit means the whole paper parses to
# zero questions, because markers are only recognized at a block's start.
#
# Only the explicit word form ("Question 3:", "Q3.") is strong enough to
# split on. A bare "3." mid-text is far too common in prose, code listings
# and figure captions to treat as a heading.
_EMBEDDED_MARKER = re.compile(r"(?=\bQ(?:uestion)?\s*\d{1,2}\s*[:.)])", re.IGNORECASE)

# The explicit heading form, and a block that merely opens with a digit.
#
# Both forms are legitimate question markers in real papers ("Question 4:"
# and "7 The diagram shows..." alike), but a bare leading number is also
# what page numbers and running headers look like — "1 National University
# of ..., Fall 2022" is a page footer, not question 1. Deciding per-span is
# guesswork; deciding per-document is not, because a paper that labels one
# question "Question 1:" labels all of them that way. So when a document
# contains any explicit heading, only explicit headings open questions
# there, and bare numbers are treated as the page furniture they are.
_EXPLICIT_HEADING = re.compile(r"^\s*Q(?:uestion)?[\s.]*\d{1,2}", re.IGNORECASE)
_OPENS_WITH_DIGIT = re.compile(r"^\s*\d")


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


def _split_embedded_markers(spans: list[SpanLike]) -> list[SpanLike]:
    """Break a span wherever an explicit question heading appears mid-text.

    The pieces keep the original span's id and page: they're still that
    span's content, just re-cut so each question's text starts where the
    question actually starts. Because the id is reused, a question can end
    up citing the same span twice — [parse_questions] de-duplicates.
    """
    out: list[SpanLike] = []
    for span in spans:
        pieces = [p.strip() for p in _EMBEDDED_MARKER.split(span.text) if p.strip()]
        if len(pieces) <= 1:
            out.append(span)
            continue
        out.extend(SpanLike(id=span.id, page=span.page, text=p) for p in pieces)
    return out


def _dedupe(span_ids: list[UUID]) -> list[UUID]:
    """Order-preserving unique. One span re-cut by [_split_embedded_markers]
    can contribute several pieces to the same question, and question_spans
    has a (question_id, source_span_id) primary key that a repeat would
    violate.
    """
    return list(dict.fromkeys(span_ids))


def _accumulate(spans: list[SpanLike]) -> list[tuple[QuestionNumber, list[SpanLike]]]:
    """Group spans under the question marker that opened them.

    A question number can legitimately reappear later in a document — a
    repeated running header, a question continued after a figure, or a
    paper that restates "Question 4" above its answer space. Those spans
    belong to the question already opened, so they're merged into it rather
    than starting a second group: two groups with the same number would
    collide on the (document_id, question_ref) uniqueness constraint and
    abort ingestion of the whole paper.
    """
    groups: list[tuple[QuestionNumber, list[SpanLike]]] = []
    index_of: dict[QuestionNumber, int] = {}
    current: QuestionNumber | None = None

    prepared = _split_embedded_markers(spans)
    explicit_only = any(_EXPLICIT_HEADING.match(s.text) for s in prepared)

    for span in prepared:
        if (
            explicit_only
            and _OPENS_WITH_DIGIT.match(span.text)
            and not _EXPLICIT_HEADING.match(span.text)
        ):
            # A bare number in a document that labels its questions
            # explicitly — page furniture. Belongs to whatever question is
            # open, and must not start a new one.
            if groups:
                groups[-1][1].append(span)
            continue

        marker = parse_question_marker(span.text, current)
        if marker is not None and marker != current:
            if marker in index_of:
                groups[index_of[marker]][1].append(span)
            else:
                index_of[marker] = len(groups)
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
                span_ids=_dedupe([s.id for s in group]),
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
                span_ids=_dedupe([s.id for s in group]),
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
