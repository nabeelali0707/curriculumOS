"""Question-number parsing and normalization.

This is the join key between a past paper and its mark scheme: the two are
separate PDFs that only line up if "1(a)(ii)" in one and "1 (a) (ii)" in
the other resolve to the same canonical form. 07_TASK_ROADMAP.md wants
question and mark-scheme entry extracted as ONE entity, and this module is
what makes that linking mechanical rather than fuzzy.

FLAGGED: the pilot exam board is undecided (09_RISKS_AND_OPEN_QUESTIONS.md
lists it as flag-don't-decide), so this supports the conventions common
across Cambridge/Edexcel/AQA rather than committing to one:

    1(a)(ii)   1 (a) (ii)   Q1(a)   Question 1   5b   1.1   (a)   (ii)

Once a board is chosen, tighten these patterns to that board's actual
convention — a narrower parser makes fewer wrong guesses than this one.
Anything unrecognized returns None and is reported, never silently
dropped.
"""

import re
from dataclasses import dataclass

# Roman numerals used for sub-parts in practice — (i) through (viii) covers
# real papers; nothing uses (ix)+ as a question sub-part.
_ROMAN_SUBPARTS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii"}

# "1(a)(ii)" / "Q1(a)" / "Question 1 (a) (ii)"
_NUM_PAREN = re.compile(
    r"^\s*(?:Q(?:uestion)?[\s.]*)?(\d{1,2})\s*\(\s*([a-z])\s*\)"
    r"(?:\s*\(\s*([a-z]{1,5})\s*\))?",
    re.IGNORECASE,
)
# "5b" / "5b(ii)" — part adjacent to the number, no space (a real convention;
# requiring adjacency avoids swallowing "1 a diagram shows..." as part 'a').
_NUM_ADJACENT = re.compile(
    r"^\s*(?:Q(?:uestion)?[\s.]*)?(\d{1,2})([a-z])"
    r"(?:\s*\(\s*([a-z]{1,5})\s*\))?(?=[\s.:)]|$)",
    re.IGNORECASE,
)
# "1.1" / "05.2" — AQA-style numeric sub-part.
_NUM_DOTTED = re.compile(
    r"^\s*(?:Q(?:uestion)?[\s.]*)?(\d{1,2})\.(\d{1,2})(?=[\s.:)]|$)",
    re.IGNORECASE,
)
# "1" / "1." / "Question 1" / "Question 1:"
# The colon matters: "Question 1:" is the dominant heading form in real
# papers, and without it every question in such a paper goes unrecognized
# and the whole document parses to zero questions.
_NUM_ONLY = re.compile(
    r"^\s*(?:Q(?:uestion)?[\s.]*)?(\d{1,2})[.):]?(?=\s|$)",
    re.IGNORECASE,
)
# "(a)" / "(a)(ii)" — continuation, inherits the number in scope.
_PART_ONLY = re.compile(
    r"^\s*\(\s*([a-z])\s*\)(?:\s*\(\s*([a-z]{1,5})\s*\))?",
    re.IGNORECASE,
)
# "(ii)" — continuation sub-part, inherits number and part in scope.
_SUBPART_ONLY = re.compile(r"^\s*\(\s*([a-z]{1,5})\s*\)(?=[\s.:]|$)", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class QuestionNumber:
    """A question's position within one paper. Not globally unique — combine
    with year + paper to get the `question_ref` the schema stores.
    """

    number: int
    part: str | None = None
    subpart: str | None = None

    def canonical(self) -> str:
        """Stable string form used for paper <-> mark-scheme matching."""
        out = f"q{self.number}"
        if self.part is not None:
            out += f".{self.part}" if self.part.isdigit() else self.part
        if self.subpart is not None:
            out += self.subpart
        return out

    def full_ref(self, *, year: int | None, paper_ref: str | None) -> str:
        """The `exam_questions.question_ref` form from 03_DATA_MODELS.md,
        e.g. "2024_p2_q5b". Omits parts that aren't known rather than
        inventing placeholders.
        """
        pieces = [str(year) if year is not None else None, paper_ref, self.canonical()]
        return "_".join(p for p in pieces if p)


def _normalize_subpart(raw: str | None) -> str | None:
    if raw is None:
        return None
    lowered = raw.lower()
    return lowered if lowered in _ROMAN_SUBPARTS else None


def match_question_marker(
    text: str, current: QuestionNumber | None = None
) -> tuple[QuestionNumber, int] | None:
    """Like [parse_question_marker], but also returns where the marker ends,
    so callers can separate the marker from the content that follows it.
    """
    if not text or not text.strip():
        return None

    if (m := _NUM_PAREN.match(text)) is not None:
        return (
            QuestionNumber(int(m.group(1)), m.group(2).lower(), _normalize_subpart(m.group(3))),
            m.end(),
        )

    if (m := _NUM_ADJACENT.match(text)) is not None:
        return (
            QuestionNumber(int(m.group(1)), m.group(2).lower(), _normalize_subpart(m.group(3))),
            m.end(),
        )

    if (m := _NUM_DOTTED.match(text)) is not None:
        return QuestionNumber(int(m.group(1)), m.group(2), None), m.end()

    # Continuation forms need context. "(ii)" is checked before "(a)" only
    # when it's a roman numeral AND a part is in scope — otherwise "(i)"
    # would always read as part 'i' rather than sub-part 'i'.
    if (m := _SUBPART_ONLY.match(text)) is not None:
        candidate = m.group(1).lower()
        if candidate in _ROMAN_SUBPARTS and current is not None and current.part is not None:
            return QuestionNumber(current.number, current.part, candidate), m.end()

    if (m := _PART_ONLY.match(text)) is not None:
        if current is not None:
            return (
                QuestionNumber(
                    current.number, m.group(1).lower(), _normalize_subpart(m.group(2))
                ),
                m.end(),
            )
        return None

    if (m := _NUM_ONLY.match(text)) is not None:
        return QuestionNumber(int(m.group(1)), None, None), m.end()

    return None


def parse_question_marker(
    text: str, current: QuestionNumber | None = None
) -> QuestionNumber | None:
    """Parse a question marker from the START of `text`.

    `current` supplies the context a continuation marker inherits: "(b)"
    means question 3 part b only if we're already inside question 3. A
    continuation marker with no context in scope is unresolvable, and
    returns None rather than guessing a number.
    """
    matched = match_question_marker(text, current)
    return matched[0] if matched is not None else None


def strip_question_marker(text: str, current: QuestionNumber | None = None) -> str:
    """`text` with any leading question marker removed.

    Needed wherever the marker is structural rather than content — most
    importantly when harvesting a mark scheme's acceptable answers, since
    "1 (a) osmosis / diffusion" should yield "osmosis" and "diffusion",
    not "1 (a) osmosis".
    """
    matched = match_question_marker(text, current)
    return text if matched is None else text[matched[1] :].strip()
