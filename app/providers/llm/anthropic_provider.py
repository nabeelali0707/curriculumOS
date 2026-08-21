from anthropic import APIError, APIStatusError, AsyncAnthropic

from app.config import Settings
from app.providers.base import LLMMessage, LLMProvider, LLMResponse, ProviderError

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        try:
            response = await self._client.messages.create(
                model=self._model,
                system=system,
                messages=turns,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (APIError, APIStatusError) as exc:
            raise ProviderError(f"anthropic: {exc}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            provider=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
