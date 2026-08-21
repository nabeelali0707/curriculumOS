from app.config import get_provider_config, get_settings
from app.providers.embeddings.qwen_provider import QwenEmbeddingProvider
from app.providers.router import ProviderRouter

_EMBEDDING_PROVIDERS = {
    "qwen3-embedding:0.6b": QwenEmbeddingProvider,
}


def get_embedding_router() -> ProviderRouter:
    config = get_provider_config()["embeddings"]
    settings = get_settings()
    provider_cls = _EMBEDDING_PROVIDERS[config["primary"]]
    provider = provider_cls(settings)
    # No retry/circuit-breaker config for embeddings yet — per
    # 04_PROVIDER_STRATEGY.md, embedding provider swaps are a re-indexing
    # job, not a per-call failover, so this router mainly exists for the
    # uniform call-site interface today.
    return ProviderRouter(provider)
