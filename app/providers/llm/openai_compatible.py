"""Shared implementation for the many LLM providers that speak the OpenAI
chat-completions wire format (Groq, OpenRouter, Together, Fireworks,
Ollama, ...). Only base_url / api_key / default model differ between them
— see the thin per-provider modules in this package.
"""

from openai import APIError, APIStatusError, AsyncOpenAI

from app.providers.base import LLMMessage, LLMProvider, LLMResponse, ProviderError


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str | None,
        requires_api_key: bool = True,
    ):
        if requires_api_key and not api_key:
            raise ValueError(f"{name}: no API key configured")
        self.name = name
        self._model = model
        # Local providers (Ollama) don't check the key; the SDK still wants
        # a non-empty string.
        self._client = AsyncOpenAI(api_key=api_key or "not-required", base_url=base_url)

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
            raise ProviderError(f"{self.name}: {exc}") from exc

        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            provider=self.name,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
