"""Turns a syllabus (or textbook table-of-contents) SourceDocument into a
CurriculumNode/CurriculumEdge tree — the missing step between "spans exist"
and "the mapper/scheduler have nodes to work with" (07_TASK_ROADMAP.md P0).

LLM-driven structural extraction, same trust posture as app/generation/:
every node gets origin=MACHINE_EXTRACTED and a confidence < 1.0 so a teacher
can tell it apart from an official/teacher-defined node, per
02_ARCHITECTURE.md §3. Not verify-then-render (there's no fact to verify
here, just a structure to propose) — the correction loop
(app/api/corrections.py) is what "verifies" this, later, when a teacher
edits it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from app.llm_json import loads_llm_json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    CurriculumEdge,
    CurriculumNode,
    EdgeType,
    NodeType,
    Origin,
    SourceSpan,
)
from app.providers.base import LLMMessage, ProviderError

logger = logging.getLogger(__name__)

# ponytail: first ~15000 chars of the document's spans, not the whole
# document — enough for a syllabus's table of objectives, cheap on tokens.
# Upgrade path: chunk + merge if a real syllabus overflows this.
MAX_CHARS = 15000

EXTRACTION_PROMPT = (
    "Below is text extracted from a subject syllabus. Extract its curriculum "
    "structure as topics, subtopics, and learning objectives, with prerequisite "
    "relationships between objectives where the text implies an ordering "
    "(e.g. one objective clearly builds on another).\n\n"
    "Text:\n{text}\n\n"
    "Respond with JSON only, this exact shape:\n"
    '{{"nodes": [\n'
    '  {{"ref": "<short unique code>", "type": "topic"|"subtopic"|"objective", '
    '"label": "...", "parent_ref": "<ref of parent, or null for a top-level topic>", '
    '"prerequisite_refs": ["<ref>", ...]}}\n'
    "]}}\n"
    "prerequisite_refs is only meaningful for type=objective and may be empty. "
    "Every non-topic node must have a parent_ref pointing to an already-listed ref."
)


class CurriculumExtractionError(ValueError):
    """Raised when the LLM response isn't the expected JSON shape, or the
    document has no spans to extract from. Same posture as ClaimParseError:
    don't guess, don't persist a half-parsed tree.
    """


@dataclass
class ExtractedNode:
    ref: str
    node_type: NodeType
    label: str
    parent_ref: str | None
    prerequisite_refs: list[str]


def _parse_extraction(raw_text: str) -> list[ExtractedNode]:
    try:
        data = loads_llm_json(raw_text)
    except json.JSONDecodeError as exc:
        raise CurriculumExtractionError(f"extraction response was not valid JSON: {exc}") from exc

    nodes_raw = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise CurriculumExtractionError("expected a non-empty top-level 'nodes' list")

    nodes: list[ExtractedNode] = []
    for item in nodes_raw:
        if not isinstance(item, dict) or "ref" not in item or "label" not in item:
            raise CurriculumExtractionError(f"malformed node entry: {item!r}")
        try:
            node_type = NodeType(str(item.get("type", "objective")).lower())
        except ValueError as exc:
            raise CurriculumExtractionError(f"unknown node type in {item!r}") from exc
        nodes.append(
            ExtractedNode(
                ref=str(item["ref"]),
                node_type=node_type,
                label=str(item["label"]),
                parent_ref=str(item["parent_ref"]) if item.get("parent_ref") else None,
                prerequisite_refs=[str(r) for r in item.get("prerequisite_refs", [])],
            )
        )
    return nodes


class CurriculumExtractionService:
    def __init__(self, session: AsyncSession, generation_chain=None):
        self._session = session
        self._generation_chain = generation_chain

    async def _get_chain(self):
        if self._generation_chain is not None:
            return self._generation_chain
        from app.providers.llm import get_generation_chain

        return get_generation_chain()

    async def extract(self, document_id: UUID) -> list[CurriculumNode]:
        spans = (
            (
                await self._session.execute(
                    select(SourceSpan)
                    .where(SourceSpan.document_id == document_id)
                    .order_by(SourceSpan.page, SourceSpan.block_id)
                )
            )
            .scalars()
            .all()
        )
        if not spans:
            raise CurriculumExtractionError(f"document {document_id} has no extracted spans")

        text = "\n".join(s.text for s in spans)[:MAX_CHARS]
        prompt = EXTRACTION_PROMPT.format(text=text)

        chain = await self._get_chain()
        try:
            response = await chain.call(
                lambda p: p.complete([LLMMessage(role="user", content=prompt)], max_tokens=4096)
            )
        except ProviderError as exc:
            raise CurriculumExtractionError(f"generation chain unavailable: {exc}") from exc

        extracted = _parse_extraction(response.text)

        nodes_by_ref: dict[str, CurriculumNode] = {}
        for item in extracted:
            node = CurriculumNode(
                node_type=item.node_type,
                label=item.label,
                syllabus_ref=item.ref,
                origin=Origin.MACHINE_EXTRACTED,
                confidence=0.7,
            )
            self._session.add(node)
            nodes_by_ref[item.ref] = node
        await self._session.flush()  # populate node.id for the edges below

        for item in extracted:
            child = nodes_by_ref[item.ref]
            if item.parent_ref and item.parent_ref in nodes_by_ref:
                self._session.add(
                    CurriculumEdge(
                        source_node_id=child.id,
                        target_node_id=nodes_by_ref[item.parent_ref].id,
                        edge_type=EdgeType.PART_OF,
                        confidence=0.7,
                        origin=Origin.MACHINE_EXTRACTED,
                    )
                )
            for prereq_ref in item.prerequisite_refs:
                if prereq_ref in nodes_by_ref:
                    self._session.add(
                        CurriculumEdge(
                            source_node_id=nodes_by_ref[prereq_ref].id,
                            target_node_id=child.id,
                            edge_type=EdgeType.PREREQUISITE,
                            confidence=0.6,
                            origin=Origin.MACHINE_INFERRED,
                        )
                    )

        await self._session.commit()
        for node in nodes_by_ref.values():
            await self._session.refresh(node)
        return list(nodes_by_ref.values())
