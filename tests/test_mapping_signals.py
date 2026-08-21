from app.mapping.signals import (
    SignalScores,
    combine,
    cosine_similarity,
    lexical_overlap,
    terminology_match,
)


def test_lexical_overlap_identical_texts_is_one():
    assert lexical_overlap("enzyme active site", "enzyme active site") == 1.0


def test_lexical_overlap_disjoint_texts_is_zero():
    assert lexical_overlap("enzymes catalyse reactions", "photosynthesis chlorophyll") == 0.0


def test_terminology_match_counts_hit_fraction():
    terms = ["active site", "substrate", "denatured"]
    node_text = "Enzyme structure: active site and substrate binding"
    assert terminology_match(terms, node_text) == 2 / 3


def test_terminology_match_empty_terms_is_zero():
    assert terminology_match([], "anything") == 0.0


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_combine_averages_present_signals_only():
    scores = SignalScores(embedding=0.8, lexical=0.4, terminology=None, llm=None)
    weight, confidence = combine(scores)
    assert weight == confidence
    assert abs(weight - 0.6) < 1e-9


def test_combine_no_signals_is_zero():
    assert combine(SignalScores()) == (0.0, 0.0)


def test_combine_missing_llm_lowers_confidence_vs_if_it_had_scored_high():
    with_llm = combine(SignalScores(embedding=0.9, lexical=0.9, terminology=0.9, llm=0.9))
    without_llm = combine(SignalScores(embedding=0.9, lexical=0.9, terminology=0.9, llm=None))
    assert without_llm[1] <= with_llm[1]
