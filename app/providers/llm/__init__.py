from app.config import get_provider_config, get_settings
from app.providers.llm.anthropic_provider import AnthropicLLMProvider
from app.providers.llm.openai_provider import OpenAILLMProvider
from app.providers.router import ProviderRouter

_LLM_PROVIDERS = {
    "anthropic": AnthropicLLMProvider,
    "openai": OpenAILLMProvider,
}


def _build_router(capability: str) -> ProviderRouter:
    config = get_provider_config()["llm"][capability]
    settings = get_settings()
    provider_cls = _LLM_PROVIDERS[config["primary"]]
    provider = provider_cls(settings)
    return ProviderRouter(
        provider,
        retry_attempts=config["retry"]["attempts"],
        backoff_seconds=config["retry"]["backoff_seconds"],
        circuit_breaker_threshold=config["circuit_breaker"]["failure_threshold"],
        circuit_breaker_cooldown_seconds=config["circuit_breaker"]["cooldown_seconds"],
    )


def get_generation_router() -> ProviderRouter:
    """LLM calls that draft content. Lower trust stakes than verification."""
    return _build_router("generation")


def get_verification_router() -> ProviderRouter:
    """LLM calls that check a generated claim against its cited evidence.

    Must use a different provider than get_generation_router() — see
    config/providers.yaml. This is the product's core trust mechanism:
    a model should not grade its own homework.
    """
    generation_provider = get_provider_config()["llm"]["generation"]["primary"]
    verification_provider = get_provider_config()["llm"]["verification"]["primary"]
    if generation_provider == verification_provider:
        raise ValueError(
            "config/providers.yaml: llm.verification.primary must differ from "
            "llm.generation.primary (see 04_PROVIDER_STRATEGY.md)"
        )
    return _build_router("verification")
