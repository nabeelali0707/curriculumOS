import pytest

from app.domain.models import NodeType
from app.ingestion.curriculum_extraction import CurriculumExtractionError, _parse_extraction


def test_parses_nodes_with_hierarchy_and_prerequisites():
    nodes = _parse_extraction(
        """
        {"nodes": [
          {"ref": "BIO.CELL", "type": "topic", "label": "Cell Biology", "parent_ref": null},
          {"ref": "BIO.CELL.01", "type": "objective", "label": "Describe mitosis",
           "parent_ref": "BIO.CELL", "prerequisite_refs": ["BIO.CELL.00"]}
        ]}
        """
    )
    assert len(nodes) == 2
    assert nodes[0].node_type is NodeType.TOPIC
    assert nodes[0].parent_ref is None
    assert nodes[1].node_type is NodeType.OBJECTIVE
    assert nodes[1].parent_ref == "BIO.CELL"
    assert nodes[1].prerequisite_refs == ["BIO.CELL.00"]


def test_missing_prerequisite_refs_defaults_to_empty():
    nodes = _parse_extraction('{"nodes": [{"ref": "A", "type": "topic", "label": "A"}]}')
    assert nodes[0].prerequisite_refs == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '{"nodes": []}',  # empty tree is a failed extraction, not a valid one
        '{"nodes": [{"ref": "A"}]}',  # no label
        '{"nodes": [{"ref": "A", "type": "galaxy", "label": "A"}]}',  # unknown node type
        '["A", "B"]',  # bare list, not the documented shape
    ],
)
def test_malformed_responses_raise_rather_than_persist_a_partial_tree(raw):
    with pytest.raises(CurriculumExtractionError):
        _parse_extraction(raw)
