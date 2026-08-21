from app.config import Settings
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

BASE_URL = "https://openrouter.ai/api/v1"
# NOTE: OpenRouter is a router in its own right (hundreds of models behind
# one API) — this default is just this provider's fallback pick, not a
# recommendation. Verify against OpenRouter's current catalog/pricing.
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"


class OpenRouterLLMProvider(OpenAICompatibleLLMProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        super().__init__(
            name="openrouter",
            model=model,
            base_url=BASE_URL,
            api_key=settings.openrouter_api_key,
        )
