"""Qwen3-Embedding, served behind an OpenAI-compatible /v1/embeddings
endpoint. Default target is a local Ollama instance running
`qwen3-embedding:0.6b` — Ollama exposes the same OpenAI-compatible
/v1/embeddings route its chat models use, so no separate client is needed.

Pass a different `base_url`/`model` (e.g. a vLLM/TEI deployment) if you
outgrow the 0.6B model — the request/response shape is identical, only
those two values change. 04_PROVIDER_STRATEGY.md still calls for a ~200-pair
retrieval benchmark before locking in any embedding model; don't treat
0.6B as a final choice, it's the cheapest thing that runs locally for P0.
"""

import httpx

from app.config import Settings
from app.providers.base import EmbeddingProvider, EmbeddingResponse, ProviderError

MAX_INPUT_TOKENS = 32_000  # per Qwen3-Embedding docs (0.6B/4B/8B share this) — reverify before relying on it
DEFAULT_MODEL = "qwen3-embedding:0.6b"


class QwenEmbeddingProvider(EmbeddingProvider):
    max_input_tokens = MAX_INPUT_TOKENS

    def __init__(
        self,
        settings: Settings,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
    ):
        self.name = model
        # Ollama's OpenAI-compatible routes live under the same base URL as
        # its chat completions (see OLLAMA_BASE_URL) — reuse it by default
        # instead of a separate embedding-specific setting.
        self._base_url = base_url or settings.ollama_base_url
        self._api_key = settings.embedding_provider_api_key  # unset for local Ollama
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = await self._client.post(
                "/embeddings",
                json={"model": self.name, "input": texts},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc

        payload = response.json()
        vectors = [item["embedding"] for item in payload["data"]]
        return EmbeddingResponse(vectors=vectors, model=self.name, provider=self.name)
