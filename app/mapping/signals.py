"""Pure scoring functions for the question -> curriculum-objective ensemble
(04_PROVIDER_STRATEGY.md §4). No DB session, no provider SDK — same
"testable without infrastructure" pattern as app/ingestion/question_parser.py.

Each signal returns a float in [0, 1]. `combine` is the fallback/consensus
policy: an unweighted average of whichever signals actually ran, so a
missing LLM signal (provider down) lowers the pooled confidence instead of
blocking the mapping — per §4, "fall back to the non-LLM signals ... and
lower the resulting confidence accordingly."
"""

import re
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def lexical_overlap(question_text: str, node_text: str) -> float:
    """Jaccard similarity of the two texts' word sets."""
    a, b = _tokens(question_text), _tokens(node_text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def terminology_match(acceptable_terms: list[str], node_text: str) -> float:
    """Fraction of the mark scheme's acceptable answer terms that appear in
    the node's syllabus label/description. Distinct from `lexical_overlap`:
    this checks whether the *expected answer vocabulary* — the strongest
    signal a mark scheme gives about what an objective actually is — shows
    up in the objective, not generic word overlap between the full
    question stem and the node text.
    """
    if not acceptable_terms:
        return 0.0
    node_tokens = _tokens(node_text)
    if not node_tokens:
        return 0.0
    hits = sum(1 for term in acceptable_terms if _tokens(term) & node_tokens)
    return hits / len(acceptable_terms)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    # Cosine similarity ranges [-1, 1]; embeddings of relevant text pairs
    # are near-orthogonal at worst in practice, but clamp defensively so
    # this never drags a combined score negative.
    return max(0.0, dot / (norm_a * norm_b))


@dataclass
class SignalScores:
    embedding: float | None = None
    lexical: float | None = None
    terminology: float | None = None
    llm: float | None = None

    def present(self) -> dict[str, float]:
        return {
            name: value
            for name, value in (
                ("embedding", self.embedding),
                ("lexical", self.lexical),
                ("terminology", self.terminology),
                ("llm", self.llm),
            )
            if value is not None
        }


def combine(scores: SignalScores) -> tuple[float, float]:
    """Returns (weight, confidence) for a QuestionNodeMapping row.

    weight = confidence = the mean of whatever signals ran. They're the
    same number here because the ensemble has no separate notion of "how
    strongly this question covers the objective" apart from "how sure the
    ensemble is that it does" — human correction (confidence 1.0, applied
    by the caller, not this function) is the only signal that would pull
    them apart, and that overwrite happens at the mapping-service layer.
    """
    present = scores.present()
    if not present:
        return 0.0, 0.0
    value = sum(present.values()) / len(present)
    return value, value
