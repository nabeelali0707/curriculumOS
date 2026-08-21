"""Pure functions for the historical assessment emphasis score.

The module deliberately knows nothing about persistence so the decay and
mapping-weight rules can be checked independently of a database.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EmphasisWeights:
    """Weights for the formula, kept configurable as the product is evaluated."""

    frequency: float = 0.2
    recency: float = 0.2
    marks: float = 0.2
    syllabus: float = 0.2
    structural: float = 0.2


@dataclass(frozen=True)
class EmphasisComponents:
    """The five auditable inputs retained alongside a computed score."""

    frequency: float
    recency: float
    marks: float
    syllabus: float
    structural: float


def recency_weight(year: int, current_year: int, decay: float = 0.2) -> float:
    """Decay older papers so historical volume cannot look current forever."""
    if decay < 0.0:
        raise ValueError("decay must be non-negative")
    return math.exp(-decay * max(0, current_year - year))


def frequency_contribution(mapping_weight: float) -> float:
    """Use mapping strength so a multi-objective question is not double-counted."""
    return max(0.0, mapping_weight)


def recency_contribution(
    year: int,
    current_year: int,
    mapping_weight: float,
    decay: float = 0.2,
) -> float:
    """Combine mapping strength with decay so recent relevant coverage dominates."""
    return frequency_contribution(mapping_weight) * recency_weight(
        year, current_year, decay
    )


def calculate_emphasis(
    components: EmphasisComponents,
    weights: EmphasisWeights | None = None,
) -> float:
    """Combine auditable signals without allowing past papers to replace syllabus data."""
    weights = weights or EmphasisWeights()
    return (
        weights.frequency * components.frequency
        + weights.recency * components.recency
        + weights.marks * components.marks
        + weights.syllabus * components.syllabus
        + weights.structural * components.structural
    )


def historical_assessment_emphasis_score(
    components: EmphasisComponents,
    weights: EmphasisWeights | None = None,
) -> float:
    """Expose the product term explicitly so callers cannot confuse it with prediction."""
    return calculate_emphasis(components, weights)