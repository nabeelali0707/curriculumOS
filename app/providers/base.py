"""Provider-agnostic interfaces. Nothing outside app/providers/ may import
a provider SDK directly (anthropic, openai, docling, ...) — everything
goes through these interfaces via the ProviderRouter, per
08_AGENT_BUILD_INSTRUCTIONS.md.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ProviderError(Exception):
    """Raised for a single failed call. The router decides whether to retry."""


class ProviderUnavailableError(ProviderError):
    """Raised when a provider's circuit breaker is open — do not attempt the call."""


class ExtractionBlockKind(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"
    LIST_ITEM = "list_item"


@dataclass
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class ExtractedBlock:
    """One structural unit of a parsed document — the atom that a
    source_span row is built from. Never a flattened page of text.
    """

    block_id: str
    page: int
    kind: ExtractionBlockKind
    text: str
    bbox: BoundingBox
    reading_order: int
    confidence: float = 1.0


@dataclass
class ParsedDocument:
    blocks: list[ExtractedBlock] = field(default_factory=list)
    parser_confidence: float = 1.0
    parser_name: str = ""


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int


@dataclass
class EmbeddingResponse:
    vectors: list[list[float]]
    model: str
    provider: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


class EmbeddingProvider(ABC):
    name: str
    max_input_tokens: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResponse: ...


class ParserProvider(ABC):
    name: str

    @abstractmethod
    async def parse(self, file_path: str) -> ParsedDocument: ...
