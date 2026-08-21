import logging

from app.config import Settings, get_provider_config, get_settings
from app.providers.llm.anthropic_provider import AnthropicLLMProvider
from app.providers.llm.fireworks_provider import FireworksLLMProvider
from app.providers.llm.groq_provider import GroqLLMProvider
from app.providers.llm.ollama_provider import OllamaLLMProvider, OllamaVerifyLLMProvider
from app.providers.llm.openai_provider import OpenAILLMProvider
from app.providers.llm.openrouter_provider import OpenRouterLLMProvider
from app.providers.llm.together_provider import TogetherLLMProvider
from app.providers.router import FallbackChain, ProviderRouter

logger = logging.getLogger(__name__)

_LLM_PROVIDERS = {
    "anthropic": AnthropicLLMProvider,
    "openai": OpenAILLMProvider,
    "groq": GroqLLMProvider,
    "openrouter": OpenRouterLLMProvider,
    "together": TogetherLLMProvider,
    "fireworks": FireworksLLMProvider,
    "ollama": OllamaLLMProvider,
    "ollama_verify": OllamaVerifyLLMProvider,
}


def _build_chain(capability: str, settings: Settings) -> FallbackChain:
    config = get_provider_config()["llm"][capability]
    routers: list[tuple[str, ProviderRouter]] = []
    for name in config["priority"]:
        provider_cls = _LLM_PROVIDERS[name]
        try:
            provider = provider_cls(settings)
        except ValueError:
            # No API key configured for this provider — skip it rather
            # than fail the whole chain. Not a runtime provider failure,
            # so it isn't logged as a warning.
            logger.debug("llm.%s: skipping %s, not configured", capability, name)
            continue
        routers.append(
            (
                name,
                ProviderRouter(
                    provider,
                    retry_attempts=config["retry"]["attempts"],
                    backoff_seconds=config["retry"]["backoff_seconds"],
                    circuit_breaker_threshold=config["circuit_breaker"]["failure_threshold"],
                    circuit_breaker_cooldown_seconds=config["circuit_breaker"]["cooldown_seconds"],
                ),
            )
        )
    if not routers:
        raise ValueError(
            f"llm.{capability}: no provider in {config['priority']} is configured "
            "(missing API keys?) — see .env.example"
        )
    return FallbackChain(routers)


def get_generation_chain() -> FallbackChain:
    """LLM calls that draft content. Lower trust stakes than verification."""
    return _build_chain("generation", get_settings())


def get_verification_chain() -> FallbackChain:
    """LLM calls that check a generated claim against its cited evidence.

    The first *configured* provider in this chain must differ from
    generation's first configured provider — see config/providers.yaml.
    This is the product's core trust mechanism: a model should not grade
    its own homework. Config-time ordering isn't enough on its own once
    fallback is in play (if generation falls through to provider B, a
    verification chain that also starts with B would silently violate the
    rule) — callers that know which provider actually generated a claim
    should pass it in `exclude` on FallbackChain.call() too.
    """
    settings = get_settings()
    generation_primary = _build_chain("generation", settings).provider_names[0]
    verification_chain = _build_chain("verification", settings)
    if verification_chain.provider_names[0] == generation_primary:
        raise ValueError(
            "config/providers.yaml: the first configured provider in "
            "llm.verification.priority must differ from llm.generation.priority "
            "(see 04_PROVIDER_STRATEGY.md) — got "
            f"{generation_primary!r} for both"
        )
    return verification_chain
