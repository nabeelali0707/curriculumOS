from openai import APIError, APIStatusError, AsyncOpenAI

from app.config import Settings
from app.providers.base import LLMMessage, LLMProvider, LLMResponse, ProviderError

# NOTE: verify this against OpenAI's current model lineup before relying on
# it in production — 04_PROVIDER_STRATEGY.md flags all provider-specific
# names/pricing as needing a check, not a hardcode-and-trust.
DEFAULT_MODEL = "gpt-4.1"


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (APIError, APIStatusError) as exc:
            raise ProviderError(f"openai: {exc}") from exc

        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            provider=self.name,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )
