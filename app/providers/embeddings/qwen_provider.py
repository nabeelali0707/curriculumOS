"""Qwen3-Embedding-8B, served behind an OpenAI-compatible /v1/embeddings
endpoint (e.g. vLLM or TEI) — this model is self-hosted, not a vendor API.

FLAGGED GAP: no hosting decision has been made yet (which inference server,
GPU sizing, where it runs). EMBEDDING_PROVIDER_BASE_URL must point at a
real deployment before this provider is usable; there is no cloud fallback
wired for P0. 04_PROVIDER_STRATEGY.md also calls for a ~200-pair retrieval
benchmark before locking in this model — don't treat the choice as final
until that's run.
"""

import httpx

from app.config import Settings
from app.providers.base import EmbeddingProvider, EmbeddingResponse, ProviderError

MAX_INPUT_TOKENS = 32_000  # per Qwen3-Embedding-8B docs — reverify before relying on it


class QwenEmbeddingProvider(EmbeddingProvider):
    name = "qwen3-embedding-8b"
    max_input_tokens = MAX_INPUT_TOKENS

    def __init__(self, settings: Settings, base_url: str | None = None):
        self._base_url = base_url or "http://localhost:8080"
        self._api_key = settings.embedding_provider_api_key
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = await self._client.post(
                "/v1/embeddings",
                json={"model": self.name, "input": texts},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"qwen3-embedding-8b: {exc}") from exc

        payload = response.json()
        vectors = [item["embedding"] for item in payload["data"]]
        return EmbeddingResponse(vectors=vectors, model=self.name, provider=self.name)
